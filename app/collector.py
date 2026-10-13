"""Сборщик результатов: из результатов блоков делает «Портрет личности».

Если от одного спектра пришло несколько реализаций (от пары команд),
выбирается лучшая по критериям: корректность формата → полнота → скорость.
Блок, не приславший результат или приславший битый, попадает в портрет
со статусом "missing"/"invalid" — данные не теряются молча.
"""
import time
from datetime import datetime, timezone

from .methods.base import RESULT_FIELDS


def check_result_format(result):
    """Возвращает список проблем формата (пустой — результат корректен)."""
    if not isinstance(result, dict):
        return ["результат не является словарём"]
    problems = [f"нет поля {f}" for f in RESULT_FIELDS if f not in result]
    if problems:
        return problems
    for field in ("score", "max_score", "percent"):
        if not isinstance(result[field], (int, float)):
            problems.append(f"поле {field} не число")
    if not problems and not 0 <= result["score"] <= result["max_score"]:
        problems.append("score вне диапазона 0..max_score")
    if not problems and not 0 <= result["percent"] <= 1:
        problems.append("percent вне диапазона 0..1")
    if not isinstance(result["skipped"], list):
        problems.append("skipped должен быть списком")
    return problems


class Collector:
    def __init__(self):
        # {method_id: [{"team": str, "result": dict, "elapsed": float}, ...]}
        self._submissions = {}

    def submit(self, result, team="default", elapsed=0.0):
        """Принять результат блока. Идентификация: method_id + team."""
        method_id = result.get("method_id") if isinstance(result, dict) else None
        if not method_id:
            raise ValueError("результат без method_id отклонён")
        self._submissions.setdefault(method_id, []).append(
            {"team": team, "result": result, "elapsed": elapsed})

    @staticmethod
    def _rank(sub):
        res = sub["result"]
        valid = not check_result_format(res)
        answered = res.get("answered", 0) if valid else 0
        # больше — лучше, поэтому знак у времени отрицательный
        return (valid, answered, -sub["elapsed"])

    def pick_best(self, method_id):
        subs = self._submissions.get(method_id, [])
        return max(subs, key=self._rank) if subs else None

    def build_portrait(self, expected_ids, person=None):
        """Единая структура по всем ожидаемым методикам."""
        sections, missing, invalid = [], [], []
        for method_id in expected_ids:
            best = self.pick_best(method_id)
            if best is None:
                missing.append(method_id)
                sections.append({"method_id": method_id, "status": "missing"})
                continue
            problems = check_result_format(best["result"])
            if problems:
                invalid.append({"method_id": method_id, "problems": problems})
                sections.append({"method_id": method_id, "status": "invalid", "problems": problems})
                continue
            sections.append({**best["result"], "source_team": best["team"]})
        return {
            "person": person or {},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sections": sections,
            "summary": {
                "expected": len(list(expected_ids)),
                "ok": sum(1 for s in sections if s.get("status") == "ok"),
                "incomplete": sum(1 for s in sections if s.get("status") == "incomplete"),
                "missing": missing,
                "invalid": invalid,
            },
        }


def collect_from_methods(methods, grouped_answers, person=None):
    """Удобная обёртка: прогнать ответы через блоки и собрать портрет.
    Ошибка внутри блока не рушит сборку — этот спектр помечается invalid."""
    collector = Collector()
    for method_id, answers in grouped_answers.items():
        method = methods.get(method_id)
        if method is None:
            continue
        started = time.perf_counter()
        try:
            result = method.score(answers)
        except Exception as exc:
            result = {"method_id": method_id, "error": str(exc)}
        collector.submit(result, team=f"block:{method_id}", elapsed=time.perf_counter() - started)
    return collector.build_portrait(list(grouped_answers), person=person)
