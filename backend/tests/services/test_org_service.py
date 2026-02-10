import sys
import unittest
from pathlib import Path
from time import time

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlmodel import select  # noqa: E402


class TestOrgServiceOwnerInvariant(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from app.db import get_session  # noqa: E402
            from app.errors import BadRequestError  # noqa: E402
            from app.models import OrgMembership, User  # noqa: E402
            from app.services.org_service import (  # noqa: E402
                add_or_update_member,
                create_org,
                remove_member,
            )
        except ModuleNotFoundError:
            raise unittest.SkipTest("Postgres dependencies are not available for org service tests")
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            raise unittest.SkipTest("Postgres is not available for org service tests")

        cls.get_session = get_session
        cls.BadRequestError = BadRequestError
        cls.OrgMembership = OrgMembership
        cls.User = User
        cls.create_org = create_org
        cls.add_or_update_member = add_or_update_member
        cls.remove_member = remove_member

    def _create_user(self, label: str) -> int:
        suffix = int(time() * 1000000)
        user = self.User(email=f"orgsvc_{label}_{suffix}@example.com", password_hash="x")
        with self.get_session() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
            return int(user.id)

    def _membership(self, org_id: int, user_id: int):
        with self.get_session() as session:
            return session.exec(
                select(self.OrgMembership).where(
                    self.OrgMembership.org_id == org_id,
                    self.OrgMembership.user_id == user_id,
                )
            ).first()

    def test_cannot_remove_last_owner(self) -> None:
        owner_id = self._create_user("remove_last_owner")
        org = self.create_org("remove-last-owner", owner_id)

        with self.assertRaises(self.BadRequestError) as exc:
            self.remove_member(int(org.id), owner_id)
        self.assertEqual(exc.exception.code, "bad_request")

        membership = self._membership(int(org.id), owner_id)
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, "owner")
        self.assertTrue(membership.is_active)

    def test_cannot_downgrade_last_owner(self) -> None:
        owner_id = self._create_user("downgrade_last_owner")
        org = self.create_org("downgrade-last-owner", owner_id)

        with self.assertRaises(self.BadRequestError) as exc:
            self.add_or_update_member(int(org.id), owner_id, "member")
        self.assertEqual(exc.exception.code, "bad_request")

        membership = self._membership(int(org.id), owner_id)
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, "owner")
        self.assertTrue(membership.is_active)

    def test_can_remove_or_downgrade_owner_when_second_active_owner_exists(self) -> None:
        owner_one_id = self._create_user("owner_one")
        owner_two_id = self._create_user("owner_two")
        org = self.create_org("with-two-owners", owner_one_id)
        org_id = int(org.id)

        self.add_or_update_member(org_id, owner_two_id, "owner")

        self.remove_member(org_id, owner_one_id)
        owner_one_membership = self._membership(org_id, owner_one_id)
        self.assertIsNone(owner_one_membership)

        self.add_or_update_member(org_id, owner_one_id, "owner")
        updated = self.add_or_update_member(org_id, owner_two_id, "member")
        self.assertEqual(updated.role, "member")
        self.assertTrue(updated.is_active)

        owner_two_membership = self._membership(org_id, owner_two_id)
        self.assertIsNotNone(owner_two_membership)
        self.assertEqual(owner_two_membership.role, "member")
        self.assertTrue(owner_two_membership.is_active)

        owner_one_membership = self._membership(org_id, owner_one_id)
        self.assertIsNotNone(owner_one_membership)
        self.assertEqual(owner_one_membership.role, "owner")
        self.assertTrue(owner_one_membership.is_active)


if __name__ == "__main__":
    unittest.main()
