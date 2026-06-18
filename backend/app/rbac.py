"""RBAC helpers shared by policy and org services."""

from __future__ import annotations

ORG_ROLES = {"viewer", "member", "admin", "owner"}
ROLE_ORDER = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def role_at_least(role: str, required: str) -> bool:
    return ROLE_ORDER.get(role, -1) >= ROLE_ORDER.get(required, 0)


def can_manage_member_role(actor_role: str, subject_role: str) -> bool:
    """Whether ``actor_role`` may grant or act on a membership at ``subject_role``.

    Least privilege: an actor can only manage roles at or below their own level,
    so an admin cannot create, elevate to, modify, or remove an ``owner`` and
    cannot escalate any member above the actor's own role.
    """
    return role_at_least(actor_role, subject_role)
