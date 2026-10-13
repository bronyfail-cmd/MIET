import copy
import json

from app.collector import Collector, check_result_format, collect_from_methods
from app.methods.base import Methodology, load_methodologies
from app.validator import validate

METHODS, _ = load_methodologies()


def good(method_id="critical_thinking", answered=6, **over):
    r = {"method_id": method_id, "title": "T", "score": 10.0, "max_score": 30.0, "percent": 0.33,
         "level": "низкий", "interpretation": "x", "subscales": {}, "answered": answered,
         "skipped": [], "status": "ok"}
    r.update(over)
    return r


def test_format_checks():
    assert check_result_format(good()) == []
    assert check_result_format("x")
    broken = good()
    del broken["level"]
    assert "нет поля level" in check_result_format(broken)
    assert check_result_format(good(score=99))
    assert check_result_format(good(percent=2))
    assert check_result_format(good(score="a"))


def test_portrait_contains_all_methods_no_dupes():
    answers = {mid: {q["id"]: q["options"][0]["value"] for q in m.questions()} for mid, m in METHODS.items()}
    portrait = collect_from_methods(METHODS, answers)
    ids = [s["method_id"] for s in portrait["sections"]]
    assert sorted(ids) == sorted(METHODS) and len(ids) == len(set(ids))
    assert portrait["summary"]["missing"] == []
    json.dumps(portrait)  # сериализуется


def test_missing_and_invalid_are_reported():
    c = Collector()
    c.submit(good("a"))
    c.submit({"method_id": "b", "oops": 1})
    p = c.build_portrait(["a", "b", "c"])
    statuses = {s["method_id"]: s["status"] for s in p["sections"]}
    assert statuses == {"a": "ok", "b": "invalid", "c": "missing"}
    assert p["summary"]["missing"] == ["c"]
    assert p["summary"]["invalid"][0]["method_id"] == "b"


def test_submit_without_id_rejected():
    import pytest
    with pytest.raises(ValueError):
        Collector().submit({"score": 1})


def test_best_of_pair_prefers_valid_then_complete_then_fast():
    c = Collector()
    c.submit({"method_id": "m"}, team="broken", elapsed=0.001)
    c.submit(good("m", answered=4), team="partial", elapsed=0.001)
    c.submit(good("m", answered=6), team="slow_full", elapsed=5.0)
    c.submit(good("m", answered=6), team="fast_full", elapsed=0.1)
    assert c.pick_best("m")["team"] == "fast_full"


def test_block_exception_marks_invalid():
    class Boom:
        def score(self, _):
            raise RuntimeError("crash")
    p = collect_from_methods({"x": Boom()}, {"x": {"x.1": 1}})
    assert p["sections"][0]["status"] == "invalid"


# ---------- валидатор ----------
def test_validator_ok_on_shipped_methods():
    report = validate(METHODS, [])
    assert report["ok"]
    assert all(i["level"] == "warning" for i in report["issues"])  # только «демо»


def test_validator_reports_missing_and_load_errors():
    report = validate(METHODS, [{"file": "bad.json", "error": "ValueError"}], expected_ids=["critical_thinking", "nope"])
    assert not report["ok"]
    checks = {(i["method"], i["check"]) for i in report["issues"] if i["level"] == "error"}
    assert ("nope", "presence") in checks and ("bad.json", "load") in checks


def spec_copy(mid="critical_thinking"):
    return copy.deepcopy(METHODS[mid].spec)


def test_validator_detects_broken_modules():
    # дубликаты id вопросов
    s = spec_copy(); s["questions"].append(dict(s["questions"][0]))
    r = validate({"critical_thinking": Methodology(s)})
    assert any(i["check"] == "integrity" and "дубликаты" in i["message"] for i in r["issues"])

    # пустой текст
    s = spec_copy(); s["questions"][0]["text"] = " "
    assert not validate({"critical_thinking": Methodology(s)})["ok"]

    # ключ указывает на несуществующий вариант -> подсчёт падает
    s = spec_copy("cognitive_reflection"); s["questions"][0]["correct"] = 9
    r = validate({"cognitive_reflection": Methodology(s)})
    assert not r["ok"]

    # пересечение id между методиками
    a, b = spec_copy(), spec_copy(); b["id"] = "other"
    for q in b["questions"]:
        pass
    r = validate({"critical_thinking": Methodology(a), "other": Methodology(b)})
    assert r["ok"]  # id вопросов включают id методики, пересечения нет


def test_validator_min_methods():
    assert not validate({}, [], min_methods=1)["ok"]


def test_validator_detects_bad_subscale_and_levels():
    s = spec_copy(); s["questions"][0]["subscale"] = "ghost"
    r = validate({"critical_thinking": Methodology(s)})
    assert any(i["check"] == "keys" for i in r["issues"])

    s = spec_copy(); s["levels"][-1]["upto"] = 0.9
    r = validate({"critical_thinking": Methodology(s)})
    assert any("последний уровень" in i["message"] for i in r["issues"])
