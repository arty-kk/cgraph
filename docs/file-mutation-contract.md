# File mutation contract for `backend/app/api/nodes.py`

Этот документ — **единственный источник истины** по node/file маршрутам в `backend/app/api/nodes.py`, включая контракт ответов для file-mutation операций.

## Важное про `path`

`path` передаётся как path-параметр URL (`/{path:path}`) и на клиенте должен быть URL-encoded **по сегментам пути** (например, через `frontend/src/api/utils.ts::encodePath`).

## Маршруты `backend/app/api/nodes.py`

### 1) Получить контракт файла
- **Маршрут:** `GET /api/nodes/{project_id}/{path}/contract`
- **Назначение:** вернуть lightweight контракт файла (`get_or_build_contract`).

### 2) Получить node-метаданные
- **Маршрут:** `GET /api/nodes/{project_id}/{path}/node`
- **Назначение:** вернуть node-метрики файла (`language`, `loc`, `complexity`, `fan_in`, `fan_out`, `scc_id`, `status`).

### 3) Прочитать файл
- **Маршрут:** `GET /api/nodes/{project_id}/{path}/file`
- **Назначение:** вернуть содержимое файла и признаки усечения (`truncated`, `max_chars`).

### 4) Обновить файл (mutation)
- **Маршрут:** `PUT /api/nodes/{project_id}/{path}/file`
- **Тело:** `{ "content": string }`

### 5) Создать файл (mutation)
- **Маршрут:** `POST /api/nodes/{project_id}/{path}/file`
- **Тело:** `{ "content": string | null }` (`null` эквивалентен пустой строке)
- **Фактический путь создания файла:** `POST /api/nodes/{project_id}/{path}/file` (используется как актуальный, не альтернативный/устаревший путь).

### 6) Переименовать файл (mutation)
- **Маршрут:** `POST /api/nodes/{project_id}/{path}/rename`
- **Тело:** `{ "new_path": string, "create_dirs": boolean }`

### 7) Удалить файл (mutation)
- **Маршрут:** `DELETE /api/nodes/{project_id}/{path}/file`

## Единый ответ для file-mutation операций

Операции mutation (`PUT/POST/POST rename/DELETE`) используют общий формат ответа из `backend/app/services/file_mutation_service.py`.

### Базовые поля
- `path: string`
- `saved: boolean`
- `reindexed: object | false`
- `index_status: "ok" | "rescan_scheduled" | "failed"`
- `warnings: string[]`

### Дополнительные поля (опционально)
- `rescan_task: object`
- `rescan_scheduled: boolean`
- `aborted: boolean`
- `rollback: "ok" | "skipped" | "failed"`
- `partial: boolean`
- `conflict: boolean`
- `conflict_reason: string`
- `error: string`
- `metrics_pending: boolean`

### Семантика статусов
- `index_status="ok"`: файл сохранён, инкрементальный reindex прошёл.
- `index_status="rescan_scheduled"`: файл сохранён, но инкрементальный scan прерван/ошибочен; запланирован фоновый full rescan.
- `index_status="failed"`: scan не удался и rollback восстановил исходное состояние (`saved=false`).
