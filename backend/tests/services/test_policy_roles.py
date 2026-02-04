import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.rbac import ROLE_ORDER, role_at_least  # noqa: E402


class TestPolicyRoles(unittest.TestCase):
    def test_role_ordering(self) -> None:
        self.assertTrue(role_at_least("owner", "admin"))
        self.assertTrue(role_at_least("admin", "member"))
        self.assertTrue(role_at_least("member", "viewer"))
        self.assertFalse(role_at_least("viewer", "member"))

    def test_invalid_role(self) -> None:
        self.assertFalse(role_at_least("unknown", "viewer"))
        self.assertEqual(ROLE_ORDER["viewer"], 0)


if __name__ == "__main__":
    unittest.main()
