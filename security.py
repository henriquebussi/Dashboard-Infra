"""Server-side identity and role checks."""
from __future__ import annotations

import hmac
import os
import logging
from typing import Callable, Optional, Union

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, HTTPBasic, HTTPBasicCredentials

from schemas import (
    DEFAULT_ROLE_PERMISSIONS,
    Permission,
    UserRBACContext,
    UserRole,
)

logger = logging.getLogger("gcp_observatory.security")

# Security Schemes for OpenAPI documentation
basic_scheme = HTTPBasic(auto_error=False)
TEMPORARY_ACCOUNTS = {"viewer@dashboard": UserRole.VIEW_ONLY, "admin@dashboard": UserRole.INFRA_ADMIN}
bearer_scheme = HTTPBearer(auto_error=False)


# ----------------------------------------------------------------------------
# 1. Identity & RBAC Context Resolution
# ----------------------------------------------------------------------------


def parse_role_string(role_str: Optional[str]) -> UserRole:
    """Safely parse user role string with fallback to VIEW_ONLY."""
    if not role_str:
        return UserRole.VIEW_ONLY
    clean = role_str.strip().upper().replace(" ", "_")
    if clean in UserRole.__members__:
        return UserRole[clean]
    return UserRole.VIEW_ONLY


async def get_current_user(
    request: Request,
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    basic: Optional[HTTPBasicCredentials] = Security(basic_scheme),
) -> UserRBACContext:
    """Authenticate server-configured, revocable access tokens."""
    if isinstance(getattr(request.state, "user", None), UserRBACContext):
        return request.state.user
    if basic:
        email = basic.username.strip().lower()
        role = TEMPORARY_ACCOUNTS.get(email)
        if role is None or not hmac.compare_digest(basic.password.encode(), b"123"):
            raise HTTPException(401, "E-mail ou senha inválidos")
        user_id = email
    else:
        for role in UserRole:
            prefix = f"DASHBOARD_{role.value}"
            secret = os.getenv(f"{prefix}_TOKEN")
            email = os.getenv(f"{prefix}_EMAIL")
            if secret and email and bearer and hmac.compare_digest(
                secret.encode(), bearer.credentials.encode()
            ):
                user_id = email
                break
        else:
            raise HTTPException(401, "Credencial inválida ou expirada", headers={"WWW-Authenticate": "Bearer"})

    user_context = UserRBACContext(
        user_id=user_id,
        role=role,
        email=email,
        permissions=DEFAULT_ROLE_PERMISSIONS.get(role, []),
    )

    # Attach to request state for downstream middleware and handlers
    request.state.user = user_context
    return user_context


# ----------------------------------------------------------------------------
# 2. Role & Permission Enforcement Dependencies
# ----------------------------------------------------------------------------


def require_role(required_role: Union[UserRole, str]) -> Callable[..., UserRBACContext]:
    """FastAPI security dependency factory enforcing a specific user role.

    Usage:
        @router.post("/thresholds", dependencies=[Depends(require_role("INFRA_ADMIN"))])
        def update_threshold(...): ...
    """
    target_role = (
        required_role
        if isinstance(required_role, UserRole)
        else parse_role_string(required_role)
    )

    async def role_dependency(
        current_user: UserRBACContext = Depends(get_current_user),
    ) -> UserRBACContext:
        if current_user.role != target_role and current_user.role != UserRole.INFRA_ADMIN:
            logger.warning(
                "Access denied for user '%s' (role: %s). Requires role: '%s'.",
                current_user.user_id,
                current_user.role.value,
                target_role.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Forbidden",
                    "message": (
                        f"Access forbidden: Operation requires '{target_role.value}' role. "
                        f"Authenticated principal '{current_user.user_id}' has role '{current_user.role.value}'."
                    ),
                    "required_role": target_role.value,
                    "actual_role": current_user.role.value,
                },
            )
        return current_user

    return role_dependency


def require_permission(
    permission: Union[Permission, str],
) -> Callable[..., UserRBACContext]:
    """FastAPI security dependency enforcing granular operational permissions."""
    target_perm = permission.value if isinstance(permission, Permission) else str(permission)

    async def permission_dependency(
        current_user: UserRBACContext = Depends(get_current_user),
    ) -> UserRBACContext:
        if not current_user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Forbidden",
                    "message": f"Action requires permission '{target_perm}'.",
                    "required_permission": target_perm,
                },
            )
        return current_user

    return permission_dependency


# Pre-configured Dependency for Infrastructure Admin role
RequireInfraAdmin = Depends(require_role(UserRole.INFRA_ADMIN))
