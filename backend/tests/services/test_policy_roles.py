import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.rbac import ROLE_ORDER, can_manage_member_role, role_at_least  # noqa: E402


class TestPolicyRoles(unittest.TestCase):
    def test_role_ordering(self) -> None:
        self.assertTrue(role_at_least("owner", "admin"))
        self.assertTrue(role_at_least("admin", "member"))
        self.assertTrue(role_at_least("member", "viewer"))
        self.assertFalse(role_at_least("viewer", "member"))

    def test_invalid_role(self) -> None:
        self.assertFalse(role_at_least("unknown", "viewer"))
        self.assertEqual(ROLE_ORDER["viewer"], 0)

    def test_admin_cannot_manage_owner_role(self) -> None:
        # An admin must not be able to grant or act on the owner role.
        self.assertFalse(can_manage_member_role("admin", "owner"))
        # ...but may manage roles at or below their own level.
        self.assertTrue(can_manage_member_role("admin", "admin"))
        self.assertTrue(can_manage_member_role("admin", "member"))
        self.assertTrue(can_manage_member_role("admin", "viewer"))

    def test_owner_can_manage_any_role(self) -> None:
        for subject in ("owner", "admin", "member", "viewer"):
            self.assertTrue(can_manage_member_role("owner", subject))

    def test_lower_roles_cannot_escalate(self) -> None:
        self.assertFalse(can_manage_member_role("member", "admin"))
        self.assertFalse(can_manage_member_role("viewer", "member"))
        self.assertFalse(can_manage_member_role("unknown", "viewer"))


if __name__ == "__main__":
    unittest.main()
