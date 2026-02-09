# File Mutation Response Contract

This document describes the response schema returned by file mutation endpoints:

- `POST /api/projects/{project_id}/files` (create)
- `PUT /api/nodes/{project_id}/{path}/file` (update)
- `POST /api/nodes/{project_id}/{path}/rename` (rename)
- `DELETE /api/nodes/{project_id}/{path}/file` (delete)

## Response fields

| Field | Type | Meaning |
| --- | --- | --- |
| `path` | string | The file path the operation targets (post-rename path for rename). |
| `saved` | boolean | Whether the file system mutation succeeded and remains applied. |
| `reindexed` | object/boolean | Scan result details when available; `false` when reindex did not complete. |
| `index_status` | `"ok" \| "rescan_scheduled" \| "failed"` | Indexing status for graph freshness. |
| `warnings` | string[] | Non-fatal warnings (e.g., `scan_aborted`, `scan_failed`, `rollback_*`). |
| `rescan_task` | object (optional) | Task metadata when rescan is scheduled. |
| `rescan_scheduled` | boolean (optional) | `true` when a background rescan was queued. |
| `aborted` | boolean (optional) | `true` when scan aborted due to snapshot mismatch. |
| `rollback` | `"ok" \| "skipped" \| "failed"` (optional) | Rollback outcome for failed scans. |
| `partial` | boolean (optional) | `true` when the disk write succeeded but indexing did not. |
| `conflict` | boolean (optional) | `true` when rollback was skipped due to concurrent changes. |
| `conflict_reason` | string (optional) | Conflict reason code (e.g., `concurrent_change`). |
| `error` | string (optional) | Error detail when scan failed. |
| `metrics_pending` | boolean (optional) | Graph metrics recomputation queued asynchronously. |

## State guidance

- `saved=true` means the file change was written to disk and kept.
- `index_status=ok` means graph data is fresh for the changed file(s).
- `index_status=rescan_scheduled` means the UI should prompt for a rescan.
- `index_status=failed` means the write was rolled back and graph data is not updated.

## Example: rescan scheduled after scan abort

```json
{
  "path": "src/main.py",
  "saved": true,
  "reindexed": false,
  "index_status": "rescan_scheduled",
  "warnings": ["scan_aborted"],
  "rescan_scheduled": true,
  "rescan_task": { "task_id": "abc123", "status": "pending" }
}
```
