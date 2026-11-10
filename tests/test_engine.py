import pytest

from app.engine import Survey
from app.methods.base import load_methodologies


@pytest.fixture
def methods():
    return load_methodologies()[0]


def test_flow_groups_questions_by_method_in_order(methods):
    ids = list(methods)[:2]
    if len(ids) < 2:
        pytest.skip("нужно минимум две методики")
    s = Survey(methods, ids)
    seq = [q["method_id"] for q in s.flow]
    assert seq == ([ids[0]] * len(methods[ids[0]]._items)
                   + [ids[1]] * len(methods[ids[1]]._items))
    assert s.total == len(methods[ids[0]]._items) + len(methods[ids[1]]._items)


def test_navigation_bounds(methods):
    mid = next(iter(methods))
    s = Survey(methods, [mid])
    s.prev()
    assert s.position == 0
    for _ in range(s.total + 5):
        s.next()
    assert s.position == s.total - 1 and s.is_last()


def test_answer_validation(methods):
    mid = next(iter(methods))
    s = Survey(methods, [mid])
    q = s.current()
    s.answer(q["id"], q["options"][0]["value"])
    with pytest.raises(ValueError):
        s.answer(q["id"], 99999)
    with pytest.raises(KeyError):
        s.answer("nope.1", 1)


def test_skipped_and_unvisited_are_none_in_groups(methods):
    mid = next(iter(methods))
    qs = methods[mid].questions()
    if len(qs) < 3:
        pytest.skip("нужно минимум три вопроса")
    s = Survey(methods, [mid])
    s.answer(qs[0]["id"], qs[0]["options"][0]["value"])
    s.answer(qs[1]["id"], None)
    grouped = s.grouped_answers()[mid]
    assert grouped[qs[0]["id"]] == qs[0]["options"][0]["value"]
    assert grouped[qs[1]["id"]] is None
    assert grouped[qs[2]["id"]] is None
    assert s.progress()["done"] == 2
    assert s.unanswered() == [q["id"] for q in qs[2:]]


def test_unknown_block_reported_not_fatal(methods):
    mid = next(iter(methods))
    s = Survey(methods, ["ghost", mid])
    assert s.total == len(methods[mid]._items)
    assert s.errors == [{"method_id": "ghost", "error": "блок не подключён"}]


def test_block_that_raises_is_isolated(methods):
    mid = next(iter(methods))

    class Broken:
        def questions(self):
            raise RuntimeError("boom")

    s = Survey({**methods, "broken": Broken()}, ["broken", mid])
    assert s.total == len(methods[mid]._items)
    assert s.errors[0]["method_id"] == "broken"


def test_empty_block_is_error(methods):
    class Empty:
        def questions(self):
            return []
    s = Survey({"empty": Empty()}, ["empty"])
    assert s.total == 0 and s.current() is None
