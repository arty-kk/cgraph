import sys
import unittest
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
            from app.main import app  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
