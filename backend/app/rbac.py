"""RBAC helpers shared by policy and org services."""

from __future__ import annotations

ORG_ROLES = {"viewer", "member", "admin", "owner"}
ROLE_ORDER = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def role_at_least(role: str, required: str) -> bool:
    return ROLE_ORDER.get(role, -1) >= ROLE_ORDER.get(required, 0)
