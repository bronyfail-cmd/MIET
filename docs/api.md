# API модуля

## Загрузчик методик (app/methods/base.py)
- `load_methodologies(data_dir=None) -> (methods, errors)`:
  `methods` — словарь `{id: Methodology}`, `errors` — список `{"file", "error"}`
  для битых JSON (загрузка не падает).

## Methodology
Поля: `id`, `title`, `kind` ("scale" | "choice" | "ipsative"), `demo`, `spec`.
- `questions() -> list[dict]`: формат вопроса для движка:
  `{"id": "<method>.<n>", "text": str, "type": "scale"|"choice",
    "options": [{"value": int, "label": str}, ...]}`
- `qid(n) -> str`: id вопроса `<method>.<n>`.
- `options_for(item) -> list[dict]`: варианты для шаблона; label нумеруются
  ("1) текст"), баллы ключей и скобки вида "(-3)" в label не попадают.
- `score(answers) -> dict`: результат методики (формат — docs/portrait_format.md);
  `answers = {qid: int | None}`, None = пропуск.
- `check_keys() -> list[str]`: внутренние проблемы ключей (пусто = ок).
- `level_for(percent) -> dict`: уровень по доле набранного.

## Движок (app/engine.py)
`Survey(methods: dict, method_ids: list)`
- `flow` — список вопросов: блоки идут целыми в порядке `method_ids`;
- `total`, `position`, `current()`;
- `next()`, `prev()`, `is_last()`, `is_last_in_method()`;
- `answer(qid, value)` — ValueError, если value нет среди вариантов;
- `skip(qid)` — пропуск (значение None);
- `answers` — `{qid: value | None}`;
- `grouped_answers() -> {method_id: {qid: value | None}}` — группировка по спектрам;
- `progress() -> {"done", "total", "percent"}`;
- `unanswered() -> list[qid]`;
- `errors -> [{"method_id", "error"}]`: неизвестный или упавший блок изолируется,
  опрос продолжается без него.

## Сборщик (app/collector.py)
- `check_result_format(result) -> list[str]`: пусто = формат корректен.
- `Collector.submit(result, team=None, elapsed=None)`;
- `Collector.pick_best(method_id)`: выбор лучшей реализации пары:
  корректность формата → полнота (answered) → скорость (elapsed);
- `Collector.build_portrait(method_ids) -> portrait`: missing/invalid не теряются;
- `collect_from_methods(methods, answers) -> portrait`: прямой сбор из методик.

## Валидатор (app/validator.py)
`validate(methods, load_errors, expected_ids=None, min_methods=None) -> report`
`report = {"ok": bool, "methods": [id...], "issues": [{"level", "method", "check", "message"}]}`
level: "error" (запуск запрещён) / "warning". Проверки: presence, load, format,
integrity (дубликаты id, пустые тексты), keys, sums, сценарии подсчёта.

## Веб-маршруты (app/web.py)
| Метод | Путь | Роль | Назначение |
| --- | --- | --- | --- |
| GET/POST | /register | — | регистрация студента с валидацией ФИО и группы |
| GET/POST | /login, /logout | — | вход/выход |
| POST | /survey/start | студент | создать/продолжить попытку |
| GET/POST | /survey/<id> | студент | вопрос, приём ответа (next/prev/finish) |
| GET/POST | /survey/<id>/continue | студент | экран паузы между блоками |
| GET | /result/<id> | владелец | «Портрет личности» |
| GET | /result/<id>/export.json, export.csv | владелец | экспорт попытки |
| GET | /admin | преподаватель | таблица результатов, фильтры |
| GET | /admin/export.csv | преподаватель | выгрузка результатов |
| GET | /admin/export_matrix.csv | преподаватель | матрица шкал для SPSS |
| GET | /admin/validate | преподаватель | отчёт валидатора |

## CLI
flask --app wsgi init-db | create-teacher EMAIL "ФИО" | validate | run [--port N]
