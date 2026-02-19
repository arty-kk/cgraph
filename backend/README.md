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

Bridge к sync Celery изолирован внутри `task_queue` в `_CeleryEnqueueAdapter`:
- сервисный слой остаётся async;
- фактический вызов `task.apply_async(...)` выполняется через выделенный `ThreadPoolExecutor` адаптера (один shared executor), без `asyncio.to_thread` на каждый enqueue.

Требования к lifecycle transport/producer:
- адаптер инициализируется один раз на процесс;
- при контролируемом завершении процесса можно явно вызвать `shutdown_celery_enqueue_adapter()` для корректного `executor.shutdown(...)`.
