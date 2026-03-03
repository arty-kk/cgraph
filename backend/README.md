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
- publish path использует ARQ enqueue (`enqueue_job`) поверх Redis и общий ARQ pool runtime;
- сервисный слой остаётся полностью async;
- enqueue выполняется без `asyncio.to_thread`, `run_coroutine_threadsafe`, loop-thread глобалей и bridge-timeout логики;
- `submit_*_async` вызывают только async producer-клиент и маппят transport-ошибки в `ExternalServiceError` с `task_id`/`queue`/`enqueue_reason`.

- обработчики task queue находятся в `app.task_handlers` и вызываются ARQ worker через `execute_task_by_name_async`.
Lifecycle соответствует единому async-паттерну:
- один async Redis runtime на процесс: startup через `init_redis_pool_async`, cleanup через `close_redis_pool_async`;
- producer-specific runtime для task queue отсутствует;
- `app.main.lifespan` и ARQ worker startup/shutdown в `app.arq_worker` используют единый lifecycle ресурсов (DB/FS/CPU/external I/O/S3/OpenAI/scan runtime).
- для ARQ cron-задач используйте явный флаг `STUBGRAPH_ARQ_ENABLE_CRON=true` только у одного worker-контейнера.
- запуск воркеров поддерживается только через `arq app.arq_worker.WorkerSettings` (runtime hooks `on_startup/on_shutdown` в `app.arq_worker`).
- стабильность ARQ worker регулируется runtime-параметрами: `STUBGRAPH_ARQ_MAX_TRIES`, `STUBGRAPH_ARQ_JOB_TIMEOUT_SECONDS`, `STUBGRAPH_ARQ_KEEP_RESULT_SECONDS`, `STUBGRAPH_ARQ_POLL_DELAY_SECONDS`.

Ожидаемая конфигурация Redis для enqueue:
- `STUBGRAPH_REDIS_URL` задаёт единый Redis broker для enqueue и runtime; queue по умолчанию задаётся через `STUBGRAPH_TASK_QUEUE_DEFAULT`.

## Background task notes

- `stubgraph.routing_calibration`: устранена причина падения фоновой задачи из-за `NameError` (`asyncio` теперь импортируется в `app.services.routing_calibration_service`).
