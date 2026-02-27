# Backend cache lifecycle

Кэш-слой в `app.infra.cache` работает только в async-режиме:
- используйте `cache_get_json_async`, `cache_set_json_async`, `cache_invalidate_prefix_async`;
- sync API для Redis/cache не поддерживается.

Для корректной работы воркера/API необходимо управлять lifecycle Redis-пула:
- при старте вызывать `init_redis_pool_async`;
- при остановке вызывать `close_redis_pool_async`.

Фактическое подключение lifecycle уже сделано в `app.main.lifespan`:
- startup: `init_redis_pool_async`;
- shutdown: `close_redis_pool_async`.


Patch storage в `app.storage` также работает только в async-режиме:
- используйте `store_patch_blob_async`, `read_patch_blob_async`, `delete_patch_blob_async`, `delete_patch_blob_by_sha_async`, `get_patch_download_url_async`;
- sync API для patch blob не поддерживается.

## Task queue async contract

`app.services.task_queue` предоставляет async boundary для постановки задач в очередь только через:
- `submit_run_async`;
- `submit_scan_async`;
- `submit_docs_async`;
- `submit_mutation_indexing_async`.

Публикация задач выполняется через awaitable producer API транспорта:
- publish path использует только общий async Redis runtime (`get_async_redis_client`) и не создаёт отдельный producer-клиент;
- сервисный слой остаётся полностью async;
- enqueue выполняется без `asyncio.to_thread`, `run_coroutine_threadsafe`, loop-thread глобалей и bridge-timeout логики;
- `submit_*_async` вызывают только async producer-клиент и маппят transport-ошибки в `ExternalServiceError` с `task_id`/`queue`/`enqueue_reason`.

Lifecycle соответствует единому async-паттерну:
- один async Redis runtime на процесс: startup через `init_redis_pool_async`, cleanup через `close_redis_pool_async`;
- producer-specific runtime для task queue отсутствует;
- `app.main.lifespan` и worker startup/shutdown в `app.celery_tasks` используют единый Redis runtime lifecycle вместе с остальными async-ресурсами (DB/FS/CPU/external I/O/S3/OpenAI/scan runtime).

Ожидаемая конфигурация Redis для enqueue:
- `STUBGRAPH_REDIS_URL` и `STUBGRAPH_CELERY_BROKER_URL` должны указывать на совместимый Redis broker (enqueue публикуется в тот же Redis runtime).
