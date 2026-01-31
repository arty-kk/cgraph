# StubGraph → SaaS (1M DAU): финальный план со стеком по шагам

## 0) Карта стека: что появляется на каком этапе

| Область | Сейчас | Целевое решение | Этап включения |
|---|---|---|---|
| API | FastAPI | FastAPI (без смены) | 0 (как есть) |
| ORM/модели | SQLModel | SQLModel + Alembic migrations | 1 |
| DB | SQLite | PostgreSQL 16 | 1 |
| Full‑text search | SQLite FTS5 | Postgres tsvector/GIN (+опц. pg_trgm) | 1 |
| Очередь/фоновые задачи | in‑memory ThreadPoolExecutor | Celery workers + RabbitMQ broker | 3 |
| Хранилище больших артефактов | локальный диск инстанса | S3‑compatible object storage (+ signed URLs) | 2 |
| Кэш/ratelimit | нет | Redis (cache + rate limit + counters) | 5 |
| Auth | нет | OAuth2/OIDC + JWT/refresh + API keys | 6 |
| Multi‑tenant/RBAC | нет | Orgs/Memberships/Roles + policy layer (+опц. Postgres RLS) | 7 |
| Семантика | опционально/завязано на LLM ключ | Embeddings pipeline + vector search (pgvector) | 8 |
| Observability | базовые логи | OpenTelemetry + Prometheus + Grafana + alerts | 9 (минимум — 0) |
| Deploy | локально | Docker Compose (dev/stage) + Kubernetes (prod) | 0 и 9 |
| Billing/Entitlements | нет | Plans/Usage/Entitlements + webhooks via queue | 9 |

---

## 1) Этапы (в каждом — что добавляем и чем именно)

### Этап 0 — Foundation: контейнеризация, окружения, контракты
**Цель:** воспроизводимые среды + безопасные релизы.
**Стек на этапе:**
- Docker (backend/frontend), Docker Compose (dev/stage).
- Конфигурация через env; раздельно dev/stage/prod.
- Логи: structured logging + `request_id` (минимум).

**Deliverables:**
- `Dockerfile` backend, `Dockerfile` frontend.
- `docker-compose.yml` (backend, frontend; доп. сервисы можно добавить позже).
- `/.env.example`, минимальный config‑профиль.
- `/api/v1` (версионирование) + контрактные тесты на ключевые ручки.

**DoD:**
- сервис поднимается одной командой в compose;
- `/api/v1` стабилен и покрыт контрактными тестами;
- в логах есть `request_id`.

---

### Этап 1 — Data: PostgreSQL + Alembic + новый search‑слой
**Цель:** durability + управляемые миграции.
**Стек на этапе:**
- PostgreSQL 16.
- Alembic (миграции) + SQLModel.
- Поиск: Postgres `tsvector`/GIN (опц. `pg_trgm`).

**Deliverables:**
- Alembic init + миграции для текущих таблиц.
- Перевод DB URL на Postgres (env).
- Замена FTS5 на Postgres search (выделить search‑слой, чтобы не вшивать в роуты).

**DoD:**
- SQLite/FTS5 не используется;
- `alembic upgrade head` обязателен перед стартом;
- поиск не хуже текущего по функциональности.

---

### Этап 2 — Artifacts: object storage вместо локального диска
**Цель:** убрать зависимость от диска инстанса (обязательное условие для scale‑out).
**Стек на этапе:**
- S3‑compatible object storage (dev может быть локальная S3‑совместимая реализация).
- Signed URLs для скачивания больших артефактов.
- Storage abstraction (local/s3).

**Deliverables:**
- Интерфейс `Storage` + реализации `LocalStorage` и `S3Storage`.
- Перенос “больших патчей”/артефактов/снимков в object storage.
- Retention‑политики (TTL/лимиты).

**DoD:**
- артефакты доступны независимо от того, на каком инстансе выполнялась задача;
- ссылки на скачивание безопасны и ограничены по времени.

---

### Этап 3 — Async: Celery + RabbitMQ + worker‑пулы + идемпотентность
**Цель:** гарантированная обработка задач при рестартах и масштабировании.
**Стек на этапе:**
- RabbitMQ (broker).
- Celery (workers + periodic при необходимости).
- Хранение статусов задач: Postgres (таблица jobs/runs), без зависимости от Redis.

**Deliverables:**
- Замена in‑memory `TaskQueue` на Celery.
- Разделение очередей/пулов: `heavy / medium / light`.
- Идемпотентность задач + retries/backoff + DLQ (для критичных).

**DoD:**
- рестарт не “теряет” задачи;
- можно горизонтально добавить workers;
- heavy задачи не душат API.

---

### Этап 4 — SaaS Ingestion: источники кода вместо локального `root_path`
**Цель:** SaaS‑совместимая поставка репозитория.
**Стек на этапе:**
- Source abstraction: upload snapshot (zip/tar) и/или git clone (через интеграцию/токен).
- Sandbox для распаковки/клонирования/скана (лимиты CPU/RAM/FS).
- Object storage (из этапа 2) для хранения “repo snapshot”.

**Deliverables:**
- Модель `RepoSnapshot` (content hash, метаданные, ссылка на storage).
- Пайплайн: source → snapshot → scan/index/graph → results.
- Инкрементальные сканы по file hash (минимум).

**DoD:**
- проект создаётся без доступа к локальному FS пользователя;
- скан воспроизводим по snapshot’у;
- есть лимиты на размер/кол-во файлов/время.

---

### Этап 5 — Redis: cache + rate limit + counters/throttling
**Цель:** производительность и защита от abuse.
**Стек на этапе:**
- Redis.
- Rate limit: token bucket/leaky bucket на Redis.
- Cache namespace + TTL.

**Deliverables:**
- Cache‑слой (ключи, TTL, инвалидация).
- Rate‑limit middleware (IP/User/API‑key).
- Throttling по тенанту (N параллельных heavy задач), счётчики, distributed locks (при необходимости).

**DoD:**
- измеримый cache hit ratio;
- API выдерживает пики без деградации Postgres;
- тяжёлые операции ограничены.

---

### Этап 6 — Identity: auth, сессии, API‑ключи
**Цель:** закрыть API и сделать multi-user базу.
**Стек на этапе:**
- OAuth2/OIDC.
- JWT access + refresh tokens (или server‑side sessions).
- API keys для automation (хэширование + ротация + revoke).

**Deliverables:**
- User/Identity/Sessions.
- Auth middleware на защищённых маршрутах.
- Управление ключами (create/list/revoke).

**DoD:**
- анонимный доступ закрыт;
- есть устойчивый механизм сессий/ключей;
- аудит ключевых security‑действий.

---

### Этап 7 — Multi‑tenant: Organizations + RBAC + policy layer
**Цель:** изоляция данных и контроль доступа для команд.
**Стек на этапе:**
- Org/Membership/Roles в Postgres.
- Policy layer (центральная авторизация).
- (Опционально) Postgres RLS для усиленной изоляции.

**Deliverables:**
- Привязка всех данных (Project/Run/Artifacts) к org/tenant.
- Единая точка проверки прав (policy).
- Тесты на изоляцию (negative cases).

**DoD:**
- пользователь видит только ресурсы своей org;
- роли реально ограничивают действия.

---

### Этап 8 — Semantic & LLM Governance: embeddings + vector search + бюджеты
**Цель:** управляемые LLM‑затраты и предсказуемый retrieval.
**Стек на этапе:**
- Vector search: pgvector (в Postgres) или отдельный vector store (если потребуется позже).
- Embeddings pipeline: Celery heavy queue.
- Usage metering: Postgres + enforcement.

**Deliverables:**
- Индексация чанков + эмбеддинги + гибридный поиск (keyword + vector).
- Учёт затрат (tokens/time/cost) по tenant/org.
- Квоты/бюджеты/приоритизация, отмена задач.

**DoD:**
- семантика работает “из коробки” и масштабируется воркерами;
- есть лимиты/квоты и понятная аналитика использования.

---

### Этап 9 — Monetization + Observability + Prod Infra
**Цель:** эксплуатационная зрелость, монетизация, готовность к 1M DAU.
**Стек на этапе:**
- Billing: Plans/Subscriptions/Entitlements + webhooks через RabbitMQ/Celery.
- Observability: OpenTelemetry (traces), Prometheus (metrics), Grafana (dashboards), alerting.
- Prod: Kubernetes, autoscaling (API и worker‑пулы), managed DB/cache/broker где возможно.
- Edge: CDN/WAF/лимиты на входе.

**Deliverables:**
- Entitlements enforcement в API и workers.
- SLO (latency/error), алерты по queue depth, scan duration, LLM usage.
- Runbooks + регулярные restore‑тесты бэкапов.
- Нагрузочные тесты + capacity план.

**DoD:**
- мониторинг/алерты покрывают API и фоновые задачи;
- деплой/роллбек стандартный;
- подтверждена устойчивость под нагрузкой.

---

## 2) Критический путь (минимальный)
0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
