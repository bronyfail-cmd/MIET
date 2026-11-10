"""Контракт тематического блока (методики).

Каждая методика описывается JSON-файлом в app/methods/data/ и загружается
классом Methodology. Движок опроса знает только про интерфейс
questions() / score(), а логику ключей и интерпретации держит сама методика.

Формат вопроса (то, что получает движок):
    {"id": "<method>.<n>", "text": str, "type": "scale" | "choice",
     "options": [{"value": int, "label": str}, ...]}

Формат результата (то, что получает сборщик):
    {"method_id": str, "title": str, "score": float, "max_score": float,
     "percent": float, "level": str, "interpretation": str,
     "subscales": {name: {"score": float, "max": float, "percent": float}},
     "answered": int, "skipped": [question_id, ...], "status": "ok" | "incomplete"}
"""
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Если пропущено больше этой доли вопросов, результат помечается "incomplete".
MAX_SKIPPED_SHARE = 0.2

RESULT_FIELDS = (
    "method_id", "title", "score", "max_score", "percent",
    "level", "interpretation", "subscales", "answered", "skipped", "status",
)


class MethodologyError(Exception):
    """Ошибка в описании методики или в переданных ей данных."""


class Methodology:
    def __init__(self, spec):
        self.spec = spec
        self.id = spec["id"]
        self.title = spec["title"]
        self.kind = spec.get("kind", "scale")
        self.description = spec.get("description", "")
        self.demo = bool(spec.get("demo", False))
        self._items = spec["questions"]
        self._levels = spec["levels"]
        self._subscales = spec.get("subscales", {})
        self._scale = spec.get("scale", {"min": 1, "max": 5, "labels": {}})

    # ---------- вопросы ----------
    def qid(self, n):
        return f"{self.id}.{n}"

    def options_for(self, item):
        if self.kind == "choice":
            out = []
            for i, opt in enumerate(item["options"]):
                if isinstance(opt, dict):
                    value = opt.get("value", i)
                    label = str(opt.get("label", ""))
                else:
                    value = i
                    label = str(opt)
                # Убираем баллы типа "(-3)", "(-2)" из label
                label = re.sub(r'\s*\(-?\d+\)\s*', ' ', label).strip()
                # Добавляем нумерацию: "1) Вариант"
                label = f"{i+1}) {label}"
                out.append({"value": value, "label": label})
            return out
        lo, hi = self._scale["min"], self._scale["max"]
        disp = self._scale.get("display_labels", {})
        labels = self._scale.get("labels", {})
        out = []
        for v in range(lo, hi + 1):
            lab = disp.get(str(v)) or labels.get(str(v), str(v))
            if str(lab).isdigit() or (str(lab).startswith('-') and str(lab)[1:].isdigit()):
                lab = str(v)
            out.append({"value": v, "label": lab})
        return out

    def questions(self):
        out = []
        for item in self._items:
            out.append({
                "id": self.qid(item["n"]),
                "text": item["text"],
                "type": "choice" if self.kind == "choice" else "scale",
                "options": self.options_for(item),
            })
        return out

    def check_keys(self):
        """Проверка самих ключей методики (используется валидатором)."""
        problems = []
        for item in self._items:
            if self.kind == "choice":
                correct = item.get("correct")
                if not isinstance(correct, int) or not 0 <= correct < len(item.get("options", [])):
                    problems.append(f"вопрос {item['n']}: ключ {correct!r} не указывает на вариант ответа")
            elif item.get("subscale") and item["subscale"] not in self._subscales:
                problems.append(f"вопрос {item['n']}: неизвестная субшкала {item['subscale']!r}")
        previous = 0.0
        for level in self._levels:
            if level["upto"] <= previous and previous:
                problems.append("границы уровней должны возрастать")
            previous = level["upto"]
        if not self._levels or self._levels[-1]["upto"] < 1:
            problems.append("последний уровень должен покрывать значения до 1.0")
        return problems

    # ---------- подсчёт ----------
    def _item_points(self, item, value):
        """Баллы за один ответ. Бросает MethodologyError, если ответ вне допустимых."""
        if self.kind == "choice":
            if not isinstance(value, int) or not 0 <= value < len(item["options"]):
                raise MethodologyError(f"недопустимый вариант {value!r} для вопроса {item['n']}")
            return 1 if value == item["correct"] else 0
        lo, hi = self._scale["min"], self._scale["max"]
        if not isinstance(value, int) or not lo <= value <= hi:
            raise MethodologyError(f"ответ {value!r} вне шкалы {lo}..{hi} (вопрос {item['n']})")
        return lo + hi - value if item.get("reverse") else value

    def _item_max(self, item):
        return 1 if self.kind == "choice" else self._scale["max"]

    def level_for(self, percent):
        for level in self._levels:
            if percent <= level["upto"]:
                return level
        return self._levels[-1]

    def score(self, answers):
        """answers: {question_id: int | None}. None или отсутствие ключа = пропуск."""
        total = 0.0
        max_total = 0.0
        skipped = []
        sub = {}
        answered = 0
        for item in self._items:
            qid = self.qid(item["n"])
            value = answers.get(qid)
            if value is None:
                skipped.append(qid)
                continue
            points = self._item_points(item, value)
            top = self._item_max(item)
            total += points
            max_total += top
            answered += 1
            key = item.get("subscale")
            if key:
                s = sub.setdefault(key, {"score": 0.0, "max": 0.0})
                s["score"] += points
                s["max"] += top

        # Нормировка по отвеченным вопросам: пропуск не штрафует, но фиксируется.
        percent = round(total / max_total, 4) if max_total else 0.0
        too_many_skips = len(skipped) > MAX_SKIPPED_SHARE * len(self._items)
        level = self.level_for(percent)
        subscales = {}
        for key, s in sub.items():
            name = self._subscales.get(key, key)
            subscales[name] = {
                "score": s["score"], "max": s["max"],
                "percent": round(s["score"] / s["max"], 4) if s["max"] else 0.0,
            }
        return {
            "method_id": self.id,
            "title": self.title,
            "score": total,
            "max_score": max_total,
            "percent": percent,
            "level": level["name"],
            "interpretation": level["text"] if answered else "Нет ответов — вывод невозможен.",
            "subscales": subscales,
            "answered": answered,
            "skipped": skipped,
            "status": "incomplete" if too_many_skips or not answered else "ok",
        }


def load_methodologies(directory=DATA_DIR):
    """Загружает все *.json из каталога. Битые файлы не роняют приложение —
    они возвращаются вторым значением как список ошибок (их покажет валидатор)."""
    methods, errors = {}, []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
            method = Methodology(spec)
            if method.id in methods:
                raise MethodologyError(f"дубликат id методики {method.id}")
            methods[method.id] = method
        except (OSError, ValueError, KeyError, MethodologyError) as exc:
            errors.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
    return methods, errors
