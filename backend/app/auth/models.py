"""
Admin auth: users/roles/permissions (spec section 12) + customer OTP
sessions (section 11).

Passwords are bcrypt-hashed (app.core.security). OTPs are stored as a
salted hash (never plaintext) - see app.auth.otp_service (added with the
auth API layer).
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin

admin_user_roles = Table(
    "admin_user_roles",
    Base.metadata,
    Column("admin_user_id", ForeignKey("admin_users.id"), primary_key=True),
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id"), primary_key=True),
)


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    roles: Mapped[list["Role"]] = relationship(secondary=admin_user_roles, back_populates="users")


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    users: Mapped[list["AdminUser"]] = relationship(secondary=admin_user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    roles: Mapped[list["Role"]] = relationship(secondary=role_permissions, back_populates="permissions")


class OtpSession(Base, TimestampMixin):
    """
    Customer OTP verification session (spec section 11). Not tied to a
    Customer row up front, since OTP is used both for identifying an
    existing customer (pre-identification, by email/mobile) and for
    verifying a known customer_id.
    """
    __tablename__ = "otp_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    otp_session_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    mobile: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. IDENTIFY, LOGIN

    otp_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    bypassed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bypassed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SsoSession(Base, TimestampMixin):
    """
    Everyticket -> Subscription App SSO handoff (spec section 47). `nonce`
    is unique so a token can only ever be redeemed once (replay
    protection); `used` is set True on first successful redemption.
    """
    __tablename__ = "sso_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sso_session_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    customer_id: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    external_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nonce: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
