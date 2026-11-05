"""Security, Role-Based Access Control (RBAC), and Audit Middleware.

Provides:
  1. User context extraction from tokens and enterprise headers.
  2. Role and permission enforcement dependencies (e.g. require_role("INFRA_ADMIN")).
  3. Starlette AuditLoggingMiddleware that intercepts configuration mutations,
     recording who changed threshold configs, what was altered, and the timestamp.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Union

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from schemas import (
    DEFAULT_ROLE_PERMISSIONS,
    AuditActionType,
    AuditLogEntry,
    Permission,
    UserRBACContext,
    UserRole,
)
from services.audit_service import audit_service
from services.metrics_store import metrics_store

logger = logging.getLogger("gcp_observatory.security")

# Security Schemes for OpenAPI documentation
api_key_header = APIKeyHeader(name="X-User-Role", auto_error=False)
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
    role_header: Optional[str] = Security(api_key_header),
) -> UserRBACContext:
    """Extract and validate the active user's identity and RBAC context.

    Sources resolved in priority order:
      1. Pre-authenticated user in request.state.user (if set by upstream gateway)
      2. Bearer token (special tokens like 'infra-admin-token' or 'admin')
      3. Enterprise headers: 'X-User-Role', 'X-User-Id', 'X-User-Email'
      4. Default fallback: VIEW_ONLY anonymous guest
    """
    # 1. Check if already resolved in request state
    if hasattr(request.state, "user") and isinstance(request.state.user, UserRBACContext):
        return request.state.user

    user_id = request.headers.get("X-User-Id") or "viewer-service-account"
    email = request.headers.get("X-User-Email") or f"{user_id}@gcp-corp.internal"
    role: UserRole = UserRole.VIEW_ONLY

    # 2. Check Bearer Token
    if bearer and bearer.credentials:
        token = bearer.credentials.strip()
        if token in ("infra-admin-token", "admin", "secret-admin-key"):
            role = UserRole.INFRA_ADMIN
            user_id = "infra-lead-token"
            email = "infra-admin@gcp-corp.internal"
        elif token.startswith("admin:"):
            role = UserRole.INFRA_ADMIN
            user_id = token.split("admin:")[1] or "admin-user"
            email = f"{user_id}@gcp-corp.internal"

    # 3. Check X-User-Role header
    if role_header:
        role = parse_role_string(role_header)
    elif "X-User-Role" in request.headers:
        role = parse_role_string(request.headers.get("X-User-Role"))

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


# ----------------------------------------------------------------------------
# 3. RBAC Audit Logging Middleware
# ----------------------------------------------------------------------------


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Starlette middleware intercepting threshold and configuration mutations.

    Automatically records who altered configuration, what metric/threshold was modified,
    previous vs new values, and the exact UTC timestamp into the immutable audit store.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Check if request targets an auditable mutation endpoint
        is_threshold_mutation = (
            request.method in ("POST", "PUT", "PATCH", "DELETE")
            and "/thresholds" in request.url.path
        )

        if not is_threshold_mutation:
            return await call_next(request)

        # Intercept and cache request body for audit recording
        body_bytes = await request.body()
        parsed_payload: Dict[str, Any] = {}
        targeted_metric = "unknown.metric"
        reason: Optional[str] = None

        if body_bytes:
            try:
                parsed_payload = json.loads(body_bytes.decode("utf-8"))
                targeted_metric = parsed_payload.get("metric_name", "unknown.metric")
                meta = parsed_payload.get("metadata") or parsed_payload.get("custom_rule_setter_metadata") or {}
                reason = meta.get("reason") or meta.get("description")
            except Exception as e:
                logger.debug("Could not parse JSON body in audit middleware: %s", e)

        # Retrieve prior state before mutation
        prior_threshold = metrics_store.get_threshold(targeted_metric)
        prior_state = (
            {
                "warning_threshold": prior_threshold.warning_threshold,
                "critical_threshold": prior_threshold.critical_threshold,
                "operator": (
                    prior_threshold.operator.value
                    if hasattr(prior_threshold.operator, "value")
                    else str(prior_threshold.operator)
                ),
            }
            if prior_threshold
            else None
        )

        # Execute downstream route handler
        response = await call_next(request)

        # Record audit log only upon successful mutation (2xx status codes)
        if 200 <= response.status_code < 300:
            user_id = request.headers.get("X-User-Id")
            if not user_id:
                if hasattr(request.state, "user") and isinstance(request.state.user, UserRBACContext):
                    user_id = request.state.user.user_id
                else:
                    user_id = "infra-admin-operator"

            action_type = (
                AuditActionType.THRESHOLD_CREATE
                if prior_state is None
                else AuditActionType.THRESHOLD_UPDATE
            )

            new_state = {
                "warning_threshold": parsed_payload.get("warning_threshold"),
                "critical_threshold": parsed_payload.get("critical_threshold"),
                "operator": parsed_payload.get("operator", ">"),
            }

            audit_entry = audit_service.record(
                user_id=user_id,
                action_type=action_type,
                targeted_metric=targeted_metric,
                previous_value=prior_state,
                new_value=new_state,
                reason=reason or f"Threshold updated via API {request.method} {request.url.path}",
            )

            # Annotate response headers
            response.headers["X-Audit-Recorded"] = "true"
            response.headers["X-Audit-Log-Id"] = str(audit_entry.log_id)
            logger.info(
                "Audit trail recorded: user='%s', action='%s', metric='%s', log_id='%s'",
                user_id,
                action_type.value,
                targeted_metric,
                audit_entry.log_id,
            )

        return response
