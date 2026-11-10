"""Движок опроса.

Не знает ничего про конкретные методики: получает у блоков списки вопросов,
выстраивает единый поток, принимает ответы (в том числе пропуски) и отдаёт
их сгруппированными по методикам. Состояние — только в передаваемом списке
ответов, поэтому движок можно пересобирать на каждый HTTP-запрос.
"""
import logging

log = logging.getLogger(__name__)


class Survey:
    def __init__(self, methods, order=None, answers=None, position=0):
        """methods: {id: Methodology}; order: порядок методик; answers: {qid: int|None}."""
        self.errors = []          # блоки, которые не смогли отдать вопросы
        self.flow = []            # единый плоский список вопросов
        self.answers = dict(answers or {})
        ids = order or list(methods)
        for method_id in ids:
            method = methods.get(method_id)
            if method is None:
                self.errors.append({"method_id": method_id, "error": "блок не подключён"})
                continue
            try:
                questions = method.questions()
                if not questions:
                    raise ValueError("пустой список вопросов")
            except Exception as exc:  # блок может упасть как угодно — движок продолжает работу
                log.warning("блок %s не отдал вопросы: %s", method_id, exc)
                self.errors.append({"method_id": method_id, "error": str(exc)})
                continue
            for q in questions:
                self.flow.append({**q, "method_id": method_id})
        self.position = max(0, min(position, max(len(self.flow) - 1, 0)))

    # ---------- навигация ----------
    @property
    def total(self):
        return len(self.flow)

    def current(self):
        return self.flow[self.position] if self.flow else None

    def next(self):
        if self.position < self.total - 1:
            self.position += 1
        return self.position

    def prev(self):
        if self.position > 0:
            self.position -= 1
        return self.position

    def is_last(self):
        return self.position >= self.total - 1

    # ---------- ответы ----------
    def _find(self, qid):
        for q in self.flow:
            if q["id"] == qid:
                return q
        raise KeyError(f"неизвестный вопрос {qid}")

    def answer(self, qid, value):
        """Принять ответ. Значение проверяется по вариантам вопроса."""
        question = self._find(qid)
        if value is None:
            self.answers[qid] = None
            return
        allowed = {o["value"] for o in question["options"]}
        if value not in allowed:
            raise ValueError(f"недопустимый ответ {value!r} на вопрос {qid}")
        self.answers[qid] = value

    def skip(self, qid):
        self._find(qid)
        self.answers[qid] = None

    # ---------- итоги ----------
    def is_last_in_method(self):
        """True, если следующий вопрос из другой методики или поток кончился."""
        if self.position >= len(self.flow) - 1:
            return True
        return self.flow[self.position]["method_id"] != self.flow[self.position + 1]["method_id"]

    def progress(self):
        done = sum(1 for q in self.flow if q["id"] in self.answers)
        return {"done": done, "total": self.total,
                "percent": round(100 * done / self.total) if self.total else 0}

    def unanswered(self):
        """Вопросы, на которые не было ни ответа, ни явного пропуска."""
        return [q["id"] for q in self.flow if q["id"] not in self.answers]

    def grouped_answers(self):
        """{method_id: {qid: value|None}} — то, что уходит в «Сборщик результатов».
        Не посещённые вопросы считаются пропущенными (None)."""
        grouped = {}
        for q in self.flow:
            grouped.setdefault(q["method_id"], {})[q["id"]] = self.answers.get(q["id"])
        return grouped
