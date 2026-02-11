import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import task_service


class _FakeSession:
    def __init__(self, run):
        self._run = run

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, run_id):
        return self._run


def test_get_run_does_not_start_scan_from_read_path(monkeypatch):
    run = SimpleNamespace(
        id=101,
        project_id=77,
        org_id=55,
        target_path='backend/app/main.py',
        mode='analyze',
        prompt='check graph readiness',
        model_used='gpt-test',
        depth=1,
        dep_mode='contracts',
        retrieval='agentic',
        retrieval_settings_json=json.dumps({'agentic': {'max_calls': 4}}),
        apply_patch=False,
        applied_json='null',
        created_at=SimpleNamespace(isoformat=lambda: '2026-01-01T00:00:00Z'),
        result_json=json.dumps({'ok': True}),
    )

    monkeypatch.setattr(task_service, 'get_session', lambda: _FakeSession(run))
    monkeypatch.setattr(task_service, '_graph_warning', lambda project_id: task_service.GRAPH_NOT_READY_WARNING)

    scan_calls: list[tuple[int, int, bool]] = []

    def _scan_with_background(project_id: int, org_id: int, background: bool = False):
        scan_calls.append((project_id, org_id, background))
        return {'task_id': 'scan-1', 'status': 'pending'}

    monkeypatch.setattr(task_service, 'scan_with_background', _scan_with_background)

    payload = task_service.get_run(project_id=77, org_id=55, run_id=101)

    assert payload['warning'] == task_service.GRAPH_NOT_READY_WARNING
    assert 'graph_scan_task_id' not in payload
    assert 'graph_scan_status' not in payload
    assert scan_calls == []
