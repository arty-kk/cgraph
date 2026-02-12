# backend/app/services/auth_service.py
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import settings
from ..db import get_session
from ..errors import BadRequestError, NotFoundError, UnauthorizedError
from ..models import ApiKey, BootstrapSentinel, Organization, OrgMembership, User, UserSession

_BOOTSTRAP_LOCK_KEY = 104729
_BOOTSTRAP_SENTINEL_KEY = "bootstrap"


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
    try:
        iterations_int = int(iterations)
    except ValueError:
        return False
    if iterations_int <= 0:
        return False

    try:
        salt = base64.b64decode(salt_b64.encode("ascii"), validate=True)
        stored_hash_bytes = base64.b64decode(hash_b64.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        return False

    pepper = settings.auth_password_pepper.encode("utf-8")
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8") + pepper, salt, iterations_int
    )
    return hmac.compare_digest(dk, stored_hash_bytes)


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


async def _create_default_org_async(session: AsyncSession, user: User) -> Organization:
    name = "Personal"
    if isinstance(user.email, str) and "@" in user.email:
        prefix = user.email.split("@", 1)[0].strip()
        if prefix:
            name = prefix[:200]
    org = Organization(name=name, created_at=datetime.now(timezone.utc))
    session.add(org)
    await session.flush()
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
        with session.begin():
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                session.exec(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": _BOOTSTRAP_LOCK_KEY},
                )

            existing_sentinel = session.exec(
                select(BootstrapSentinel)
                .where(BootstrapSentinel.key == _BOOTSTRAP_SENTINEL_KEY)
                .limit(1)
            ).first()
            existing_user = session.exec(select(User).limit(1)).first()
            if existing_sentinel or existing_user:
                raise BadRequestError("Bootstrap уже выполнен")

            try:
                session.add(BootstrapSentinel(key=_BOOTSTRAP_SENTINEL_KEY))
                session.flush()
            except IntegrityError as exc:
                raise BadRequestError("Bootstrap уже выполнен") from exc

            user = User(email=email.strip().lower(), password_hash=_hash_password(password))
            session.add(user)
            session.flush()
            _create_default_org(session, user)
        session.refresh(user)
        return user


async def bootstrap_user_async(session: AsyncSession, email: str, password: str) -> User:
    if not isinstance(email, str) or not email.strip():
        raise BadRequestError("Email обязателен")
    if not isinstance(password, str) or len(password) < 8:
        raise BadRequestError("Пароль должен быть не короче 8 символов")

    async with session.begin():
        dialect = session.bind.dialect.name if session.bind is not None else ""
        if dialect == "postgresql":
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY})

        existing_sentinel = (
            (
                await session.execute(
                    select(BootstrapSentinel)
                    .where(BootstrapSentinel.key == _BOOTSTRAP_SENTINEL_KEY)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        existing_user = (await session.execute(select(User).limit(1))).scalars().first()
        if existing_sentinel or existing_user:
            raise BadRequestError("Bootstrap уже выполнен")

        try:
            session.add(BootstrapSentinel(key=_BOOTSTRAP_SENTINEL_KEY))
            await session.flush()
        except IntegrityError as exc:
            raise BadRequestError("Bootstrap уже выполнен") from exc

        user = User(email=email.strip().lower(), password_hash=_hash_password(password))
        session.add(user)
        try:
            session.flush()
            _create_default_org(session, user)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise BadRequestError("Пользователь уже существует") from exc
        session.refresh(user)
        return user


def register_user(email: str, password: str) -> User:
    if not settings.auth_allow_public_signup:
        raise BadRequestError("Регистрация отключена")
    if not isinstance(email, str) or not email.strip():
        raise BadRequestError("Email обязателен")
    if not isinstance(password, str) or len(password) < 8:
        raise BadRequestError("Пароль должен быть не короче 8 символов")

    with get_session() as session:
        user = User(email=email.strip().lower(), password_hash=_hash_password(password))
        session.add(user)
        try:
            session.flush()
            _create_default_org(session, user)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise BadRequestError("Пользователь уже существует") from exc
        session.refresh(user)
        return user


async def register_user_async(session: AsyncSession, email: str, password: str) -> User:
    if not settings.auth_allow_public_signup:
        raise BadRequestError("Регистрация отключена")
    if not isinstance(email, str) or not email.strip():
        raise BadRequestError("Email обязателен")
    if not isinstance(password, str) or len(password) < 8:
        raise BadRequestError("Пароль должен быть не короче 8 символов")

    user = User(email=email.strip().lower(), password_hash=_hash_password(password))
    session.add(user)
    try:
        await session.flush()
        await _create_default_org_async(session, user)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise BadRequestError("Пользователь уже существует") from exc
    await session.refresh(user)
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


async def authenticate_user_async(session: AsyncSession, email: str, password: str) -> User:
    if not isinstance(email, str) or not email.strip():
        raise BadRequestError("Email обязателен")
    if not isinstance(password, str):
        raise BadRequestError("Пароль обязателен")
    user = (
        (await session.execute(select(User).where(User.email == email.strip().lower()))).scalars().first()
    )
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


async def create_session_async(session: AsyncSession, user_id: int) -> tuple[str, datetime]:
    token, token_hash = _generate_token("sess")
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.auth_session_ttl_hours)
    session.add(
        UserSession(
            user_id=user_id,
            token_hash=token_hash,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            revoked_at=None,
        )
    )
    await session.commit()
    return token, expires_at


async def revoke_session_async(session: AsyncSession, token: str) -> None:
    token_hash = _hash_token(token)
    row = (await session.execute(select(UserSession).where(UserSession.token_hash == token_hash))).scalars().first()
    if not row:
        return
    row.revoked_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()


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


async def _get_valid_session_async(session: AsyncSession, token: str) -> UserSession | None:
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)
    row = (
        (
            await session.execute(
                select(UserSession).where(
                    UserSession.token_hash == token_hash,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
            )
        ).scalars().first()
    )
    return row


async def _get_valid_api_key_async(session: AsyncSession, token: str) -> ApiKey | None:
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc)
    row = (
        (
            await session.execute(
                select(ApiKey).where(
                    ApiKey.token_hash == token_hash,
                    ApiKey.revoked_at.is_(None),
                    (ApiKey.expires_at.is_(None) | (ApiKey.expires_at > now)),
                )
            )
        ).scalars().first()
    )
    return row


async def get_user_from_token_async(session: AsyncSession, token: str) -> User:
    user_session = await _get_valid_session_async(session, token)
    if user_session:
        user = await session.get(User, user_session.user_id)
        if user:
            return user
    key = await _get_valid_api_key_async(session, token)
    if key:
        user = await session.get(User, key.user_id)
        if user:
            return user
    raise UnauthorizedError("Неверный токен")


async def create_api_key_async(session: AsyncSession, user_id: int, name: str) -> tuple[str, ApiKey]:
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
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return token, key


async def list_api_keys_async(session: AsyncSession, user_id: int) -> list[ApiKey]:
    return list((await session.execute(select(ApiKey).where(ApiKey.user_id == user_id))).scalars().all())


async def revoke_api_key_async(session: AsyncSession, user_id: int, key_id: int) -> None:
    key = await session.get(ApiKey, key_id)
    if not key or key.user_id != user_id:
        raise NotFoundError("API key не найден")
    key.revoked_at = datetime.now(timezone.utc)
    session.add(key)
    await session.commit()
