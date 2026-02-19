# agentic

Пакет `agentic` содержит runtime-логику агентного вызова LLM: подготовку контекста, вызовы модели и диспетчеризацию инструментов.

## Runtime API (async-only)

Публичный runtime-контракт пакета — только async entrypoints:

- `analyze_agentic_async`
- `evolve_agentic_async`
- `fix_agentic_async`
- `_dispatch_tool_async`
- `_seed_context_async`
- `_agentic_json_call_async`

Синхронные runtime entrypoints не поддерживаются и не экспортируются из `app.llm.agentic`.

## Инструменты

Инструменты для runtime также вызываются через async-функции (например `*_async` из `tools.py`), которые использует `_dispatch_tool_async`.
