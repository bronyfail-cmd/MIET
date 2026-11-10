# Контракты данных

## Вопрос (методика → движок)
```json
{"id": "critical_thinking.1", "text": "…", "type": "scale|choice",
 "options": [{"value": 1, "label": "Совсем не согласен"}]}
```

### Формат options
Поддерживаются два вида `options`:
- `["строка", ...]` — список подписей; значение варианта — его индекс.
- `[{"value": int, "label": str}, ...]` — явные значение и подпись.

## Файл методики (`app/methods/data/<id>.json`)
```json
{
  "id": "critical_thinking",
  "title": "Критическое мышление",
  "kind": "scale",                       // или "choice"
  "demo": false,
  "scale": {"min": 1, "max": 5, "labels": {"1": "…"}},
  "subscales": {"analysis": "Анализ информации"},
  "questions": [
    {"n": 1, "text": "…", "subscale": "analysis", "reverse": false}
  ],
  "levels": [
    {"upto": 0.4, "name": "низкий", "text": "…"},
    {"upto": 0.7, "name": "средний", "text": "…"},
    {"upto": 1.0, "name": "высокий", "text": "…"}
  ]
}
```
- `scale`: балл = значение (для `reverse` — `min + max − значение`).
- `choice`: у вопроса `options: [...]` и `correct: <индекс верного>`; 1 балл за верный.
- Уровень выбирается по доле набранного от максимума: первый `upto`, не меньший доли.

## Результат методики (методика → сборщик)
```json
{"method_id": "…", "title": "…", "score": 21.0, "max_score": 30.0, "percent": 0.7,
 "level": "высокий", "interpretation": "…",
 "subscales": {"Анализ информации": {"score": 12, "max": 15, "percent": 0.8}},
 "answered": 6, "skipped": [], "status": "ok|incomplete"}
```

## Портрет личности (сборщик → интерфейс)
```json
{"person": {"name": "…", "group": "…"}, "generated_at": "ISO-8601",
 "sections": [ /* результат методики | {"method_id","status":"missing|invalid"} */ ],
 "summary": {"expected": 3, "ok": 3, "incomplete": 0, "missing": [], "invalid": [], "block_errors": []}}
```

## Отчёт валидатора
```json
{"ok": true, "methods": ["…"],
 "issues": [{"level": "error|warning", "method": "…", "check": "presence|load|questions|integrity|keys|format|scoring|sums|content", "message": "…"}]}
```
Проверки: наличие и загрузка методик, непустые вопросы, уникальность id,
минимум два варианта ответа, корректность ключей и уровней, пробный прогон
(все мин. / все макс. / все пропуски), формат результата, сумма субшкал = общий балл.
