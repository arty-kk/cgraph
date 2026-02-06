#backend/app/services/auth_service.py
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from ..config import settings
from ..errors import BadRequestError, NotFoundError, UnauthorizedError
from ..models import ApiKey, OrgMembership, Organization, User, UserSession
from ..db import get_session


def _hash_password(password: str, *, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    iterations = 200_000
    pepper = settings.auth_password_pepper.encode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8") + pepper, salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, hash_b64 = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    salt = base64.b64decode(salt_b64.encode("ascii"))
    calc = _hash_password(password, salt=salt)
    return hmac.compare_digest(calc, stored)


def _hash_token(token: str) -> str:
    pepper = settings.auth_password_pepper.encode("utf-8")
    return hashlib.sha256(token.encode("utf-8") + pepper).hexdigest()


def _generate_token(prefix: str) -> tuple[str, str]:
    raw = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    token = f"{prefix}_{raw}"
    return token, _hash_token(token)


def _create_default_org(session, user: User) -> Organization:
    name = "Personal"
    if isinstance(user.email, str) and "@" in user.email:
        prefix = user.email.split("@", 1)[0].strip()
        if prefix:
            name = prefix[:200]
    org = Organization(name=name, created_at=datetime.now(timezone.utc))
    session.add(org)
    session.flush()
    session.add(
        OrgMembership(
            org_id=org.id,
            user_id=user.id,
            role="owner",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
    )
    return org


def bootstrap_user(email: str, password: str) -> User:
    if not isinstance(email, str) or not email.strip():
        raise BadRequestError("Email обязателен")
    if not isinstance(password, str) or len(password) < 8:
        raise BadRequestError("Пароль должен быть не короче 8 символов")
    with get_session() as session:
        existing = session.exec(select(User).limit(1)).first()
        if existing:
            raise BadRequestError("Bootstrap уже выполнен")
        user = User(email=email.strip().lower(), password_hash=_hash_password(password))
        session.add(user)
        session.flush()
        _create_default_org(session, user)
        session.commit()
        session.refresh(user)
        return user


def register_user(email: str, password: str) -> User:
    if not settings.auth_allow_public_signup:
        raise BadRequestError("Публичная регистрация отключена")
    if not isinstance(email, str) or not email.strip():
        raise BadRequestError("Email обязателен")
    if not isinstance(password, str) or len(password) < 8:
        raise BadRequestError("Пароль должен быть не короче 8 символов")
    with get_session() as session:
        existing = session.exec(select(User).where(User.email == email.strip().lower())).first()
        if existing:
            raise BadRequestError("Пользователь уже существует")
        user = User(email=email.strip().lower(), password_hash=_hash_password(password))
        session.add(user)
        session.flush()
        _create_default_org(session, user)
        session.commit()
        session.refresh(user)
        return user


def authenticate_user(email: str, password: str) -> User:
    if not isinstance(email, str) or not email.strip():
        raise BadRequestError("Email обязателен")
    if not isinstance(password, str):
        raise BadRequestError("Пароль обязателен")
    with get_session() as session:
        user = session.exec(select(User).where(User.email == email.strip().lower())).first()
    if not user or not user.is_active:
        raise UnauthorizedError("Неверные учетные данные")
    if not _verify_password(password, user.password_hash):
        raise UnauthorizedError("Неверные учетные данные")
    return user


def create_session(user_id: int) -> tuple[str, datetime]:
    token, token_hash = _generate_token("sess")
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.auth_session_ttl_hours)
    with get_session() as session:
        session.add(
            UserSession(
                user_id=user_id,
                token_hash=token_hash,
                created_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                revoked_at=None,
            )
        )
        session.commit()
    return token, expires_at


def revoke_session(token: str) -> None:
    token_hash = _hash_token(token)
    with get_session() as session:
        row = session.exec(select(UserSession).where(UserSession.token_hash == token_hash)).first()
        if not row:
            return
        row.revoked_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()


def _get_valid_session(token: str) -> UserSession | None:
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.exec(
            select(UserSession).where(
                UserSession.token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        ).first()
    return row


def _get_valid_api_key(token: str) -> ApiKey | None:
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.exec(
            select(ApiKey).where(
                ApiKey.token_hash == token_hash,
                ApiKey.revoked_at.is_(None),
                (ApiKey.expires_at.is_(None) | (ApiKey.expires_at > now)),
            )
        ).first()
    return row


def get_user_by_id(user_id: int) -> User:
    with get_session() as session:
        user = session.get(User, user_id)
    if not user:
        raise NotFoundError("Пользователь не найден")
    return user


def get_user_from_token(token: str) -> User:
    session = _get_valid_session(token)
    if session:
        return get_user_by_id(session.user_id)
    key = _get_valid_api_key(token)
    if key:
        return get_user_by_id(key.user_id)
    raise UnauthorizedError("Неверный токен")


def create_api_key(user_id: int, name: str) -> tuple[str, ApiKey]:
    token, token_hash = _generate_token("api")
    prefix = token.split("_", 1)[0]
    expires_at = None
    if settings.auth_api_key_ttl_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.auth_api_key_ttl_days)
    key = ApiKey(
        user_id=user_id,
        name=name or "default",
        token_prefix=prefix,
        token_hash=token_hash,
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at,
        revoked_at=None,
    )
    with get_session() as session:
        session.add(key)
        session.commit()
        session.refresh(key)
    return token, key


def list_api_keys(user_id: int) -> list[ApiKey]:
    with get_session() as session:
        return session.exec(select(ApiKey).where(ApiKey.user_id == user_id)).all()


def revoke_api_key(user_id: int, key_id: int) -> None:
    with get_session() as session:
        key = session.get(ApiKey, key_id)
        if not key or key.user_id != user_id:
            raise NotFoundError("API key не найден")
        key.revoked_at = datetime.now(timezone.utc)
        session.add(key)
        session.commit()
