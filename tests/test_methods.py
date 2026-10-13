import json

import pytest

from app.methods.base import MethodologyError, load_methodologies


@pytest.fixture(scope="module")
def methods():
    m, errors = load_methodologies()
    assert errors == []
    return m


def all_answers(method, pick):
    return {q["id"]: pick(q["options"]) for q in method.questions()}


def test_all_demo_methods_loaded(methods):
    assert {"critical_thinking", "cognitive_reflection", "communication_styles"} <= set(methods)


def test_scale_max_and_min_with_reverse_keys(methods):
    m = methods["critical_thinking"]
    # максимум по каждому вопросу с учётом обратных пунктов
    best = {}
    for item in m._items:
        best[m.qid(item["n"])] = 1 if item.get("reverse") else 5
    res = m.score(best)
    assert res["score"] == res["max_score"] == 30
    assert res["level"] == "высокий"
    worst = {k: (5 if v == 1 else 1) for k, v in best.items()}
    assert m.score(worst)["score"] == 6
    assert m.score(worst)["level"] == "низкий"


def test_subscales_sum_to_total(methods):
    m = methods["communication_styles"]
    res = m.score(all_answers(m, lambda o: o[1]["value"]))
    assert sum(s["score"] for s in res["subscales"].values()) == res["score"]


def test_choice_keys(methods):
    m = methods["cognitive_reflection"]
    right = {"cognitive_reflection.1": 1, "cognitive_reflection.2": 2, "cognitive_reflection.3": 1}
    assert m.score(right)["score"] == 3
    assert m.score(right)["level"] == "высокий"
    wrong = {"cognitive_reflection.1": 0, "cognitive_reflection.2": 0, "cognitive_reflection.3": 0}
    assert m.score(wrong)["score"] == 0


@pytest.mark.parametrize("bad", [0, 6, -1, "3", 2.5])
def test_out_of_scale_answer_rejected(methods, bad):
    with pytest.raises(MethodologyError):
        methods["critical_thinking"].score({"critical_thinking.1": bad})


def test_skip_all_is_incomplete(methods):
    m = methods["critical_thinking"]
    res = m.score({})
    assert res["status"] == "incomplete"
    assert res["answered"] == 0
    assert len(res["skipped"]) == 6


def test_few_skips_ok_many_skips_incomplete(methods):
    m = methods["communication_styles"]  # 5 вопросов, порог 20% => 1 пропуск допустим
    answers = all_answers(m, lambda o: o[2]["value"])
    answers["communication_styles.1"] = None
    assert m.score(answers)["status"] == "ok"
    answers["communication_styles.2"] = None
    assert m.score(answers)["status"] == "incomplete"


def test_broken_json_does_not_crash_loader(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "nokeys.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
    methods, errors = load_methodologies(tmp_path)
    assert methods == {}
    assert {e["file"] for e in errors} == {"broken.json", "nokeys.json"}
