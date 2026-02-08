# StubGraph — продуктовое описание

## 1. Краткое описание
StubGraph — это платформа для анализа исходного кода, которая строит граф файлов/зависимостей и даёт рабочее пространство для поиска, навигации, редактирования и запуска LLM‑задач поверх выбранного проекта. В составе есть API на FastAPI и фронтенд с визуальным графом, деревом файлов, встроенным редактором и панелью задач. Система поддерживает загрузку проектов из локального пути или из snapshot‑архива, индексацию (scan), построение графа, поиск (включая семантический при включённых embeddings), генерацию проектной документации и запуск LLM‑тасков (analyze/evolve/fix/impact).【F:backend/app/main.py†L1-L73】【F:backend/app/api/projects.py†L1-L210】【F:backend/app/api/nodes.py†L1-L440】【F:backend/app/api/tasks.py†L1-L140】【F:frontend/src/ui/App.tsx†L1-L496】

## 2. Целевая аудитория и ключевая ценность
**Кому полезно**
- Разработчикам и техлидам, которым нужно быстро понять структуру большого репозитория, зависимости между файлами и «горячие» узлы кода (fan‑in/fan‑out/complexity).【F:backend/app/models.py†L90-L137】【F:backend/app/services/project_service.py†L140-L206】
- Командам, которым требуется совместная работа через организации и роли (owner/admin/member/viewer).【F:backend/app/api/orgs.py†L1-L86】
- Пользователям, которым нужен управляемый LLM‑поток для анализа/фикса/эволюции кода и генерации документации на основе контекста проекта.【F:backend/app/api/tasks.py†L1-L140】【F:backend/app/services/docs_service.py†L1-L66】

**Ключевая ценность**
- Быстрая навигация по большому коду через граф зависимостей и богатый контекст (метрики, контракты, поиск).【F:backend/app/api/projects.py†L73-L210】【F:backend/app/api/nodes.py†L1-L440】
- Единый интерфейс для обзора, редактирования и запуска интеллектуальных задач (LLM) прямо из UI.【F:frontend/src/ui/App.tsx†L235-L746】【F:frontend/src/ui/components/NodePanel.tsx†L1-L200】

## 3. Основные пользовательские сценарии
1. **Создать организацию и проект**: пользователь создаёт организацию, затем добавляет проект либо по локальному пути, либо через загрузку snapshot‑архива (zip/архив), после чего проект доступен в UI. Ограничения на локальный путь задаются настройками (allow_local_root_path).【F:backend/app/api/orgs.py†L1-L51】【F:backend/app/api/projects.py†L29-L76】【F:backend/app/services/project_service.py†L47-L92】【F:backend/app/config.py†L41-L63】
2. **Запустить Scan и построить граф**: проект индексируется, формируются узлы и рёбра, рассчитываются метрики (complexity/fan‑in/fan‑out), после чего UI отображает граф и файлы проекта.【F:backend/app/api/projects.py†L87-L132】【F:backend/app/services/project_service.py†L229-L284】
3. **Навигация и поиск**: пользователь ищет узлы по имени, выполняет текстовый или семантический поиск, открывает файл/узел и просматривает его контракт и метрики.【F:backend/app/api/projects.py†L133-L189】【F:backend/app/api/nodes.py†L63-L156】
4. **Редактирование**: файл открывается во встроенном редакторе (включая diff‑режим и навигацию по зависимостям), изменения сохраняются через API с повторным индексированием и обновлением метрик графа.【F:frontend/src/ui/components/FileEditorPane.tsx†L1-L160】【F:backend/app/api/nodes.py†L164-L440】
5. **LLM‑задачи**: на выбранном файле запускается задача анализа/эволюции/фикса/оценки импакта; система поддерживает agentic или pack‑режим подготовки контекста, хранит историю запусков и позволяет применять патчи к файлам проекта.【F:backend/app/api/tasks.py†L1-L140】【F:backend/app/services/task_service.py†L1-L120】
6. **Генерация документации**: пользователь строит «project docs», которые формируются на основе структуры проекта и результатов индексации, и затем просматривает их в UI (Markdown).【F:backend/app/api/projects.py†L191-L210】【F:backend/app/services/docs_service.py†L1-L66】【F:frontend/src/ui/App.tsx†L496-L746】

## 4. Ключевые возможности продукта
### 4.1 Управление организациями и доступом
- Организации, роли и управление участниками через API (viewer/member/admin/owner).【F:backend/app/api/orgs.py†L1-L86】
- Пользовательская аутентификация, сессии и API‑ключи (login/register, revoke).【F:backend/app/api/auth.py†L1-L88】

### 4.2 Управление проектами и источниками
- Создание проекта из локального пути (если разрешено настройкой) или из snapshot‑архива, хранение метаданных snapshot‑ов и ограничение их размера/количества файлов.【F:backend/app/api/projects.py†L29-L76】【F:backend/app/services/project_service.py†L47-L92】【F:backend/app/config.py†L41-L60】
- Полное удаление проекта с чисткой связанных сущностей (граф, документы, embeddings, результаты задач).【F:backend/app/services/project_service.py†L98-L176】

### 4.3 Индексация и граф зависимостей
- Индексация проекта и построение графа зависимостей файлов, включая метрики сложности и связности (fan‑in/out).【F:backend/app/services/project_service.py†L229-L308】【F:backend/app/models.py†L90-L137】
- Локальные подграфы для выбранного файла и настройка лимитов на количество узлов/рёбер.【F:backend/app/api/projects.py†L101-L132】【F:backend/app/services/project_service.py†L286-L308】
- UI‑визуализация графа и управление фильтрами/лейблами/фокусом.【F:frontend/src/ui/components/GraphCanvas.tsx†L1-L200】

### 4.4 Поиск
- Поиск по узлам проекта и текстовый поиск по содержимому файлов с контекстными сниппетами.【F:backend/app/api/projects.py†L133-L176】【F:backend/app/services/project_service.py†L333-L507】
- Семантический поиск при включённых embeddings и наличии соответствующих entitlement‑лимитов.【F:backend/app/services/project_service.py†L311-L331】【F:backend/app/config.py†L118-L137】

### 4.5 Файловые операции и редактор
- Просмотр/создание/изменение/удаление/переименование файлов с пересканом и обновлением метрик графа.【F:backend/app/api/nodes.py†L164-L440】
- Встроенный редактор с diff‑режимом, вкладками, поиском/replace, зависимостями файла и навигацией обратно в граф.【F:frontend/src/ui/components/FileEditorPane.tsx†L1-L200】

### 4.6 LLM‑задачи и патчи
- Запуск задач (analyze/evolve/fix/impact) с гибкими параметрами контекста и режимов (agentic/pack), хранение истории запусков и применение патчей к коду.【F:backend/app/api/tasks.py†L1-L140】【F:backend/app/services/task_service.py†L1-L220】
- UI‑панель для настройки параметров задач, просмотра результатов и управления патчами/запусками.【F:frontend/src/ui/components/NodePanel.tsx†L1-L200】

### 4.7 Генерация документации
- Генерация Markdown‑документации по проекту (overview и расширения), хранение версии документа в БД и просмотр в UI.【F:backend/app/services/docs_service.py†L1-L66】【F:backend/app/models.py†L150-L158】【F:frontend/src/ui/App.tsx†L496-L746】

## 5. Архитектура и компоненты
- **Backend**: FastAPI сервис, middleware для CORS, rate limiting и опциональной авторизации; API‑маршруты для проектов/узлов/задач/организаций/авторизации.【F:backend/app/main.py†L1-L73】
- **Task‑очередь**: Celery с раздельными очередями для scan/docs/run_task (heavy/medium/light).【F:backend/app/celery_app.py†L1-L17】
- **Frontend**: SPA на React + Vite, основной экран — граф/редактор/панель задач, модальные окна для docs/onboarding/командной палитры.【F:frontend/src/ui/App.tsx†L1-L746】
- **Хранилище**: реляционная БД через SQLModel (PostgreSQL); ключевые сущности — Project, FileNode, FileEdge, AnalysisRun, ProjectDoc, RepoSnapshot и др.【F:backend/app/models.py†L9-L237】

## 6. Основные сущности и данные
- **Project**: имя проекта, корневой путь и связь с организацией.【F:backend/app/models.py†L9-L18】
- **FileNode / FileEdge**: узлы и связи графа (path, language, loc, fan‑in/out, complexity).【F:backend/app/models.py†L90-L137】
- **AnalysisRun**: история LLM‑запусков, параметры и результат выполнения/патча.【F:backend/app/models.py†L133-L149】
- **ProjectDoc**: Markdown‑документация проекта, сформированная системой.【F:backend/app/models.py†L150-L158】
- **RepoSnapshot**: метаданные загруженных snapshot‑архивов проекта.【F:backend/app/models.py†L72-L80】

## 7. Ограничения и важные настройки
- Локальные корневые пути могут быть запрещены через настройки, в таком случае проект создаётся только через snapshot‑архивы.【F:backend/app/config.py†L41-L63】【F:backend/app/services/project_service.py†L47-L55】
- Семантический поиск зависит от включённой поддержки embeddings и лимитов энтитлементов (например, дневные лимиты запросов/чанков).【F:backend/app/services/project_service.py†L311-L331】【F:backend/app/config.py†L118-L137】
- Применение патчей контролируется настройками (например, «только внутри контекста»).【F:backend/app/config.py†L92-L97】【F:backend/app/services/task_service.py†L1-L120】

## 8. Метрики и показатели, которые логично отслеживать
- Объём индексированных файлов и узлов графа, динамика метрик риска (complexity/fan‑in/out).【F:backend/app/models.py†L90-L137】【F:backend/app/services/project_service.py†L140-L206】
- Успешность/время выполнения задач scan/docs/LLM‑runs (через TaskJob/AnalysisRun).【F:backend/app/models.py†L133-L237】【F:backend/app/celery_app.py†L1-L17】
- Уровень использования LLM/embeddings (OrgUsage, entitlements, лимиты).【F:backend/app/models.py†L41-L70】【F:backend/app/services/project_service.py†L311-L331】

---

**Итог:** StubGraph — это связка «граф кода + редактор + LLM‑задачи», которая превращает проект в navigable‑структуру, дополняемую интеллектуальными подсказками и инструментами, доступными через единый UI и API.【F:backend/app/main.py†L1-L73】【F:frontend/src/ui/App.tsx†L1-L746】
