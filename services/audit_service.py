"""Audit Logging Service for GCP FinOps Observatory.

Maintains an immutable in-memory audit trail with filtering and search capabilities,
capturing who modified threshold configurations, what was altered, previous/new values,
and the timestamp.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, List, Optional, Union
from uuid import UUID

from schemas import AuditActionType, AuditLogEntry


class AuditService:
    """Thread-safe audit trail registry for tracking configuration and threshold mutations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: List[AuditLogEntry] = []
        self._seed_default_audit_trail()

    def _seed_default_audit_trail(self) -> None:
        """Seed initial audit trail for demonstration and verification purposes."""
        seed_entries = [
            AuditLogEntry(
                user_id="lead-infra-admin@gcp-corp.internal",
                action_type=AuditActionType.THRESHOLD_CREATE,
                targeted_metric="database.cpu_io_percent",
                previous_value=None,
                new_value={"warning": 70.0, "critical": 85.0, "operator": ">"},
                reason="Baseline production threshold initialization",
            ),
            AuditLogEntry(
                user_id="sre-lead@gcp-corp.internal",
                action_type=AuditActionType.THRESHOLD_UPDATE,
                targeted_metric="cloud.cpu_percent",
                previous_value={"warning": 80.0, "critical": 95.0, "operator": ">"},
                new_value={"warning": 75.0, "critical": 90.0, "operator": ">"},
                reason="Tighter fleet autoscaling safety margins ahead of Q4 shopping peak",
            ),
            AuditLogEntry(
                user_id="finops-controller@gcp-corp.internal",
                action_type=AuditActionType.THRESHOLD_UPDATE,
                targeted_metric="tokens.cost_per_model",
                previous_value={"warning": 1500.0, "critical": 3000.0, "operator": ">"},
                new_value={"warning": 1200.0, "critical": 2500.0, "operator": ">"},
                reason="Budget guardrails updated for Vertex AI Gemini 1.5 workload",
            ),
        ]
        self._entries.extend(seed_entries)

    def record(
        self,
        user_id: str,
        action_type: Union[AuditActionType, str],
        targeted_metric: str,
        previous_value: Optional[Any] = None,
        new_value: Optional[Any] = None,
        reason: Optional[str] = None,
    ) -> AuditLogEntry:
        """Create and record an immutable audit log entry.

        Args:
            user_id: Identity of the principal who performed the mutation.
            action_type: Category of mutation (e.g. THRESHOLD_UPDATE).
            targeted_metric: Metric or configuration identifier altered.
            previous_value: State prior to mutation.
            new_value: State following mutation.
            reason: Optional justification or ticket reference.

        Returns:
            The recorded AuditLogEntry.
        """
        entry = AuditLogEntry(
            user_id=user_id,
            action_type=action_type,
            targeted_metric=targeted_metric,
            previous_value=previous_value,
            new_value=new_value,
            reason=reason,
            timestamp=datetime.now(timezone.utc),
        )
        with self._lock:
            # Store at index 0 for reverse-chronological default order
            self._entries.insert(0, entry)
        return entry

    def query(
        self,
        user_id: Optional[str] = None,
        action_type: Optional[Union[AuditActionType, str]] = None,
        targeted_metric: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AuditLogEntry]:
        """Query audit log records with filtering and pagination.

        Args:
            user_id: Optional filter for specific user ID.
            action_type: Optional filter for specific action type.
            targeted_metric: Optional filter or prefix for metric name.
            start_time: Filter records occurring at or after this UTC timestamp.
            end_time: Filter records occurring at or before this UTC timestamp.
            limit: Maximum records to return.
            offset: Number of matching records to skip.

        Returns:
            List of matching AuditLogEntry items in reverse chronological order.
        """
        with self._lock:
            results = self._entries

            if user_id:
                results = [e for e in results if user_id.lower() in e.user_id.lower()]

            if action_type:
                target_action = (
                    action_type.value
                    if isinstance(action_type, AuditActionType)
                    else str(action_type)
                )
                results = [
                    e
                    for e in results
                    if (
                        e.action_type.value
                        if isinstance(e.action_type, AuditActionType)
                        else str(e.action_type)
                    )
                    == target_action
                ]

            if targeted_metric:
                results = [
                    e
                    for e in results
                    if targeted_metric.lower() in e.targeted_metric.lower()
                ]

            if start_time:
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
                results = [e for e in results if e.timestamp >= start_time]

            if end_time:
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)
                results = [e for e in results if e.timestamp <= end_time]

            return results[offset : offset + limit]

    def get_by_id(self, log_id: Union[UUID, str]) -> Optional[AuditLogEntry]:
        """Retrieve a specific audit entry by its unique UUID."""
        target_id = UUID(str(log_id)) if not isinstance(log_id, UUID) else log_id
        with self._lock:
            for entry in self._entries:
                if entry.log_id == target_id:
                    return entry
        return None

    def count(self) -> int:
        """Return total number of recorded audit entries."""
        with self._lock:
            return len(self._entries)


# Global singleton instance for application runtime
audit_service = AuditService()
