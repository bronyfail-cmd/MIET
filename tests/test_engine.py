import pytest

from app.engine import Survey
from app.methods.base import load_methodologies


@pytest.fixture
def methods():
    return load_methodologies()[0]


def test_flow_groups_questions_by_method_in_order(methods):
    s = Survey(methods, ["critical_thinking", "cognitive_reflection"])
    ids = [q["method_id"] for q in s.flow]
    assert ids == ["critical_thinking"] * 6 + ["cognitive_reflection"] * 3
    assert s.total == 9


def test_navigation_bounds(methods):
    s = Survey(methods, ["cognitive_reflection"])
    s.prev()
    assert s.position == 0
    for _ in range(10):
        s.next()
    assert s.position == s.total - 1 and s.is_last()


def test_answer_validation(methods):
    s = Survey(methods, ["critical_thinking"])
    s.answer("critical_thinking.1", 3)
    with pytest.raises(ValueError):
        s.answer("critical_thinking.1", 99)
    with pytest.raises(KeyError):
        s.answer("nope.1", 1)


def test_skipped_and_unvisited_are_none_in_groups(methods):
    s = Survey(methods, ["cognitive_reflection"])
    s.answer("cognitive_reflection.1", 1)
    s.skip("cognitive_reflection.2")
    grouped = s.grouped_answers()["cognitive_reflection"]
    assert grouped == {"cognitive_reflection.1": 1, "cognitive_reflection.2": None,
                       "cognitive_reflection.3": None}
    assert s.progress()["done"] == 2
    assert s.unanswered() == ["cognitive_reflection.3"]


def test_unknown_block_reported_not_fatal(methods):
    s = Survey(methods, ["ghost", "cognitive_reflection"])
    assert s.total == 3
    assert s.errors == [{"method_id": "ghost", "error": "блок не подключён"}]


def test_block_that_raises_is_isolated(methods):
    class Broken:
        def questions(self):
            raise RuntimeError("boom")
    m = {**methods, "broken": Broken()}
    s = Survey(m, ["broken", "cognitive_reflection"])
    assert s.total == 3
    assert s.errors[0]["method_id"] == "broken"


def test_empty_block_is_error(methods):
    class Empty:
        def questions(self):
            return []
    s = Survey({"empty": Empty()}, ["empty"])
    assert s.total == 0 and s.current() is None
