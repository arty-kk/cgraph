# Code Surgeon (local) — интерактивная карта проекта + LLM-операции “как сверхчеловек”

Это локальный инструмент, который:
- индексирует репозиторий (файлы/импорты) и строит граф зависимостей,
- показывает интерактивную карту в браузере,
- позволяет запускать на любом файле (узле) управляемые LLM-задачи по произвольному запросу:
  - `Analyze` (диагностика/объяснение),
  - `Evolve` (точки эволюции бизнес-логики),
  - `Fix` (поведенческий фикс по ТЗ → unified diff),
  - `Impact` (кого заденет изменение).

## Стек
- Backend: **Python + FastAPI + SQLModel (SQLite)**  
- Frontend: **React + TypeScript + Vite + Tailwind + Cytoscape.js**
- LLM: **OpenAI Responses API** (мульти-модельная оркестрация: `gpt-5-nano` → triage, `gpt-5-mini` → анализ/контракты, `gpt-5` → патчи)

> Важно: API ключ **никогда** не должен попадать во фронт. Он хранится только на бэке.

---

## 0) Требования
- Python 3.11+
- Node 18+ (или 20+)
- OpenAI API key: `OPENAI_API_KEY`

---

## 1) Запуск (dev)
### Backend
```bash
cd backend
python -m venv .venv
# mac/linux:
source .venv/bin/activate
# windows (powershell):
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
export OPENAI_API_KEY="..."   # windows: setx OPENAI_API_KEY "..."
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Открой в браузере: http://localhost:5173

---

## 2) Быстрый сценарий
1) В UI укажи локальный путь к репозиторию (например: `/Users/you/dev/myrepo`).
2) Нажми **Scan** — построится граф.
3) Кликни на узел (файл) → справа панель → выбери режим и введи запрос.
   - Примеры:
     - “найти точки эволюции бизнеслогики”
     - “это работает неправильно: сейчас X, должно быть Y”
     - “объясни назначение и риски этого модуля”
4) Для `Fix` ты получишь **unified diff**. Можно применить патч в UI (опция Apply).

---

## 3) Настройки
Бэкенд читает env переменные (см. `backend/app/config.py`):
- `OPENAI_API_KEY` — ключ (обязательно для LLM задач)
- `CODESURGEON_DB_DIR` — куда класть SQLite (по умолчанию: `~/.code-surgeon`)
- `CODESURGEON_DEFAULT_DEPTH` — дефолт глубины подтягивания deps

---

## 4) Про “встроенную память” vs локальную
Этот проект использует:
1) **Локальную структурированную память** (SQLite): граф, контракты модулей, результаты задач, патчи.
2) **Сессионную память Responses API** (chain по `previous_response_id` или `conversation`) — опционально.

По документации OpenAI, `conversation` и `previous_response_id` помогают сохранять контекст между вызовами, но **все предыдущие токены всё равно биллятся как input**. Для долгих цепочек есть `/responses/compact`, чтобы “сжать” историю. (См. ссылки в UI “Docs”.)

---

## 5) Примечания
- Индексация импортов — “best effort” (Python AST + JS/TS regex + fallback). Для экзотики добавляй плагины в `backend/app/indexers/`.
- Верификация патчей (линт/тесты) зависит от проекта — это отдельный шаг. В MVP патч просто применяется; verifiers можно добавить в `backend/app/verify/`.

