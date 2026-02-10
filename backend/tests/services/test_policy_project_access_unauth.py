import sys
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine
from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import policy  # noqa: E402
from app.errors import ForbiddenError  # noqa: E402
from app.models import Organization, Project  # noqa: E402


class TestRequireProjectAccessUnauth(unittest.TestCase):
    def test_forbids_access_to_project_from_other_org(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Organization.__table__.create(engine)
        Project.__table__.create(engine)

        with Session(engine) as session:
            org1 = Organization(name="Org 1", slug="org-1")
            org2 = Organization(name="Org 2", slug="org-2")
            session.add(org1)
            session.add(org2)
            session.commit()
            session.refresh(org1)
            session.refresh(org2)
            org1_id = int(org1.id)
            org2_id = int(org2.id)

            foreign_project = Project(
                org_id=org2_id,
                name="Foreign",
                root_path="/tmp/foreign",
            )
            session.add(foreign_project)
            session.commit()
            session.refresh(foreign_project)
            foreign_project_id = int(foreign_project.id)

        def _get_session() -> Session:
            return Session(engine)

        request = Request(
            {
                "type": "http",
                "headers": [(b"x-org-id", str(org1_id).encode("utf-8"))],
            }
        )

        with (
            mock.patch("app.policy.get_session", _get_session),
            mock.patch.object(policy.settings, "auth_enabled", False),
        ):
            with self.assertRaises(ForbiddenError) as exc:
                policy.require_project_access(request, foreign_project_id)

        self.assertEqual(str(exc.exception), "Нет доступа к проекту")


if __name__ == "__main__":
    unittest.main()
