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


def first_of_kind(methods, kind):
    for mid, m in methods.items():
        if m.kind == kind:
            return mid, m
    return None, None


def test_all_methods_loaded(methods):
    from app.methods.base import DATA_DIR
    assert len(methods) == len(list(DATA_DIR.glob("*.json")))


def test_questions_contract(methods):
    """Каждый вопрос: id, текст, тип, варианты с уникальными value и строковыми label."""
    for mid, m in methods.items():
        for q in m.questions():
            assert q["id"] and q["text"].strip()
            assert q["type"] in ("scale", "choice")
            values = [o["value"] for o in q["options"]]
            assert len(values) == len(set(values))
            for o in q["options"]:
                assert isinstance(o["label"], str) and o["label"] != ""


def test_score_invariants_for_every_method(methods):
    for mid, m in methods.items():
        res = m.score(all_answers(m, lambda o: o[0]["value"]))
        assert res["status"] == "ok"
        assert 0 <= res["score"] <= res["max_score"]
        assert 0.0 <= res["percent"] <= 1.0
        assert res["level"] in {l["name"] for l in m._levels}


def test_choice_all_correct_is_max_score(methods):
    mid, m = first_of_kind(methods, "choice")
    if m is None:
        pytest.skip("нет choice-методики")
    right = {m.qid(i["n"]): i["correct"] for i in m._items if "correct" in i}
    if not right:
        pytest.skip("choice-методика без ключей")
    res = m.score(right)
    assert res["score"] == res["max_score"]
    wrong = {m.qid(i["n"]): (i["correct"] + 1) % len(i["options"])
             for i in m._items if "correct" in i}
    assert m.score(wrong)["score"] < res["score"]


@pytest.mark.parametrize("bad", [-1, 99, "3", 2.5])
def test_out_of_scale_answer_rejected(methods, bad):
    mid, m = first_of_kind(methods, "scale")
    if m is None:
        pytest.skip("нет scale-методики")
    with pytest.raises(MethodologyError):
        m.score({m.qid(1): bad})


def test_skip_all_is_incomplete(methods):
    """Полный пропуск всех вопросов даёт статус incomplete."""
    mid, m = next(iter(methods.items()))
    res = m.score({})
    assert res["status"] == "incomplete"
    assert res["answered"] == 0
    assert len(res["skipped"]) == len(m._items)


def test_many_skips_is_incomplete(methods):
    """Много пропусков даёт статус incomplete."""
    mid, m = next(iter(methods.items()))
    answers = all_answers(m, lambda o: o[0]["value"])
    for i, item in enumerate(m._items):
        if i % 2 == 0:
            answers[m.qid(item["n"])] = None
    res = m.score(answers)
    assert res["status"] == "incomplete"


def test_broken_json_does_not_crash_loader(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "nokeys.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
    methods, errors = load_methodologies(tmp_path)
    assert methods == {}
    assert {e["file"] for e in errors} == {"broken.json", "nokeys.json"}


def test_ipsative_counts_choices(methods):
    m = methods.get("communication_styles")
    if m is None:
        pytest.skip("нет ipsative-методики")
    ans = {m.qid(i["n"]): 0 for i in m._items}
    res = m.score(ans)
    assert res["status"] == "ok"
    assert sum(s["score"] for s in res["subscales"].values()) == len(m._items)
    assert res["score"] == max(s["score"] for s in res["subscales"].values())
