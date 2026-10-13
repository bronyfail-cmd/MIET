"""Валидатор: проверяет целостность модуля до запуска.

Отчёт: {"ok": bool, "methods": [...id...], "issues": [{"level", "method", "check", "message"}]}
level: "error" (модуль нельзя запускать) или "warning".
"""
from .collector import check_result_format
from .methods.base import MethodologyError


def _issue(level, method, check, message):
    return {"level": level, "method": method, "check": check, "message": message}


def validate(methods, load_errors=(), expected_ids=None, min_methods=1):
    issues = []

    for err in load_errors:
        issues.append(_issue("error", err["file"], "load", err["error"]))

    if expected_ids:
        for mid in expected_ids:
            if mid not in methods:
                issues.append(_issue("error", mid, "presence", "методика не подключена"))
    if len(methods) < min_methods:
        issues.append(_issue("error", "-", "presence", f"подключено методик: {len(methods)}, нужно ≥ {min_methods}"))

    all_qids = set()
    for mid, method in methods.items():
        try:
            questions = method.questions()
        except Exception as exc:
            issues.append(_issue("error", mid, "questions", f"блок не отдаёт вопросы: {exc}"))
            continue
        if not questions:
            issues.append(_issue("error", mid, "questions", "пустой список вопросов"))
            continue

        ids = [q["id"] for q in questions]
        if len(ids) != len(set(ids)):
            issues.append(_issue("error", mid, "integrity", "дубликаты id вопросов"))
        dup = all_qids.intersection(ids)
        if dup:
            issues.append(_issue("error", mid, "integrity", f"id пересекаются с другими методиками: {sorted(dup)}"))
        all_qids.update(ids)

        for q in questions:
            if not q.get("text", "").strip():
                issues.append(_issue("error", mid, "integrity", f"пустой текст вопроса {q['id']}"))
            if len(q.get("options", [])) < 2:
                issues.append(_issue("error", mid, "integrity", f"у вопроса {q['id']} меньше двух вариантов ответа"))

        for problem in method.check_keys():
            issues.append(_issue("error", mid, "keys", problem))

        _check_scoring(mid, method, questions, issues)

        if method.demo:
            issues.append(_issue("warning", mid, "content", "методика в ДЕМО-версии (заглушки вместо материалов заказчика)"))

    return {
        "ok": not any(i["level"] == "error" for i in issues),
        "methods": sorted(methods),
        "issues": issues,
    }


def _check_scoring(mid, method, questions, issues):
    """Пробный прогон: все минимальные, все максимальные ответы, все пропуски."""
    def answers_with(pick):
        return {q["id"]: pick(q["options"]) for q in questions}

    probes = {
        "min": answers_with(lambda o: min(x["value"] for x in o)),
        "max": answers_with(lambda o: max(x["value"] for x in o)),
        "skip": {q["id"]: None for q in questions},
    }
    for name, answers in probes.items():
        try:
            result = method.score(answers)
        except (MethodologyError, Exception) as exc:
            issues.append(_issue("error", mid, "scoring", f"подсчёт падает на сценарии '{name}': {exc}"))
            continue
        problems = check_result_format(result)
        if problems:
            issues.append(_issue("error", mid, "format", f"сценарий '{name}': " + "; ".join(problems)))
            continue
        if result["answered"] + len(result["skipped"]) != len(questions):
            issues.append(_issue("error", mid, "integrity", f"сценарий '{name}': ответы и пропуски не дают общее число вопросов"))
        if name == "skip" and result["status"] != "incomplete":
            issues.append(_issue("error", mid, "scoring", "при полном пропуске статус должен быть 'incomplete'"))
        sub_total = sum(s["score"] for s in result["subscales"].values())
        if result["subscales"] and abs(sub_total - result["score"]) > 1e-9:
            issues.append(_issue("error", mid, "sums", f"сценарий '{name}': сумма по субшкалам {sub_total} ≠ общий балл {result['score']}"))
