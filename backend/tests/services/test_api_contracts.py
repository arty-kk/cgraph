import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlmodel import select  # noqa: E402


class TestApiContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from app.db import get_session  # noqa: E402
            from app.models import OrgMembership, User  # noqa: E402
            from app.services.auth_service import bootstrap_user, create_session  # noqa: E402
        except ModuleNotFoundError:
            raise unittest.SkipTest(
                "Postgres dependencies are not available for API contract tests"
            )
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            raise unittest.SkipTest("Postgres is not available for API contract tests")

        from app.main import app  # noqa: E402

        cls.client = TestClient(app)
        with get_session() as session:
            user = session.exec(select(User).limit(1)).first()
        if not user:
            user = bootstrap_user("test@example.com", "password123")
        token, _ = create_session(user.id)
        with get_session() as session:
            membership = session.exec(
                select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
            ).first()
        if not membership:
            raise unittest.SkipTest("No org membership available for API contract tests")
        cls.headers = {
            "Authorization": f"Bearer {token}",
            "X-Org-ID": str(membership.org_id),
        }

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("repo/README.md", "hello")
        buffer.seek(0)
        response = cls.client.post(
            "/api/projects/from-snapshot",
            data={"name": "contract-project"},
            files={"archive": ("repo.zip", buffer, "application/zip")},
            headers=cls.headers,
        )
        if response.status_code != 200:
            raise unittest.SkipTest("Unable to create snapshot project for contract tests")
        cls.project_id = response.json().get("id")

    def test_health_includes_request_id(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))

    def test_projects_versioned_and_unversioned(self) -> None:
        response_v1 = self.client.get("/api/v1/projects", headers=self.headers)
        response_unversioned = self.client.get("/api/projects", headers=self.headers)
        self.assertEqual(response_v1.status_code, 200)
        self.assertEqual(response_unversioned.status_code, 200)
        self.assertEqual(response_v1.json(), response_unversioned.json())

    def test_config_contract(self) -> None:
        response = self.client.get("/api/config", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("allow_local_root_path", payload)
        self.assertIsInstance(payload["allow_local_root_path"], bool)

    def test_files_tree_contract(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.project_id}/files/tree", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("entries", payload)
        self.assertIn("meta", payload)
        self.assertIsInstance(payload["entries"], list)
        self.assertIsInstance(payload["meta"], dict)

    def test_dependencies_contract(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.project_id}/dependencies",
            params={"path": "repo/README.md"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("inbound", payload)
        self.assertIn("outbound", payload)
        self.assertIsInstance(payload["inbound"], list)
        self.assertIsInstance(payload["outbound"], list)

    def test_graph_contract(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.project_id}/graph", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)

    def test_runs_contract(self) -> None:
        response = self.client.get(
            f"/api/tasks/{self.project_id}/runs", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)


if __name__ == "__main__":
    unittest.main()
