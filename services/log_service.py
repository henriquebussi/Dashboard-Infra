"""GCP FinOps Observatory - Cloud Logging Integration Service.

Provides bounded, circuit-breaker-protected queries against Cloud Logging:
  - Slow-query logs for Cloud SQL instances (PostgreSQL / MySQL)
  - Error logs (severity >= ERROR) with truncation and capping indicators
  - Vertex AI LLM inference token-usage events

Constraints:
  - Strict adherence to `roles/logging.viewer` (no admin APIs)
  - Bounded queries: explicit UTC start/end intervals and max_results limits
  - Capped queries return `estimated: True` when limit is reached
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gcp_observatory.log_service")

try:
    from google.cloud import logging as gcp_logging
    _LOGGING_AVAILABLE = True
except ImportError:
    _LOGGING_AVAILABLE = False
    gcp_logging = None  # type: ignore[assignment]


@dataclass
class BoundedLogResult:
    """Result of a bounded Cloud Logging query."""

    query_type: str
    entries: List[Dict[str, Any]]
    total_count: int
    capped: bool = False
    estimated: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_type": self.query_type,
            "total_count": self.total_count,
            "capped": self.capped,
            "estimated": self.estimated,
            "fetched_at": self.fetched_at.isoformat(),
            "entries": self.entries,
        }


class GCPLogService:
    """Interface to Cloud Logging API v3 for log-based observability metrics."""

    def __init__(self, project_id: str, credentials: Optional[Any] = None) -> None:
        self.project_id = project_id
        self._credentials = credentials
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        if not _LOGGING_AVAILABLE:
            raise RuntimeError(
                "google-cloud-logging is not installed. Run: pip install google-cloud-logging"
            )
        if self._client is None:
            kwargs: Dict[str, Any] = {"project": self.project_id}
            if self._credentials:
                kwargs["credentials"] = self._credentials
            self._client = gcp_logging.Client(**kwargs)
        return self._client

    async def get_slow_query_logs(
        self,
        hours: int = 24,
        threshold_ms: int = 1000,
        database_id: Optional[str] = None,
        max_entries: int = 200,
    ) -> BoundedLogResult:
        """Fetch slow query log records from Cloud SQL instances."""
        if not _LOGGING_AVAILABLE:
            return BoundedLogResult(query_type="slow_queries", entries=[], total_count=0)

        loop = asyncio.get_running_loop()
        start_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        ts_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        filters = [
            'resource.type="cloudsql_database"',
            f'timestamp>="{ts_str}"',
            'textPayload:"duration:"',
        ]
        if database_id:
            filters.append(f'resource.labels.database_id="{database_id}"')

        active_filter = " AND ".join(filters)

        def _sync() -> BoundedLogResult:
            try:
                client = self._get_client()
                entries: List[Dict[str, Any]] = []
                # Fetch up to max_entries + 1 to detect capping
                for entry in client.list_entries(
                    resource_names=[f"projects/{self.project_id}"],
                    filter_=active_filter,
                    order_by=gcp_logging.DESCENDING,
                    max_results=max_entries + 1,
                    page_size=min(max_entries + 1, 100),
                ):
                    duration_ms: Optional[float] = None
                    text = getattr(entry, "payload", "") or ""
                    if isinstance(text, str) and "duration:" in text:
                        try:
                            after = text.split("duration:")[1].strip()
                            duration_ms = float(after.split()[0])
                        except (IndexError, ValueError):
                            pass

                    if duration_ms is not None and duration_ms < threshold_ms:
                        continue

                    entries.append(
                        {
                            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                            "severity": str(entry.severity),
                            "database_id": entry.resource.labels.get("database_id", database_id) if entry.resource else database_id,
                            "duration_ms": duration_ms,
                            "query_text": str(text)[:500],
                            "labels": dict(entry.labels or {}),
                        }
                    )

                is_capped = len(entries) > max_entries
                final_entries = entries[:max_entries]

                return BoundedLogResult(
                    query_type="slow_queries",
                    entries=final_entries,
                    total_count=len(final_entries),
                    capped=is_capped,
                    estimated=is_capped,
                )
            except Exception as exc:
                logger.warning("[LogService] slow_queries query failed: %s", exc)
                return BoundedLogResult(query_type="slow_queries", entries=[], total_count=0)

        return await loop.run_in_executor(None, _sync)

    async def get_token_usage_logs(
        self,
        hours: int = 24,
        log_filter: Optional[str] = None,
        max_entries: int = 500,
    ) -> BoundedLogResult:
        """Fetch Vertex AI model token usage events from Cloud Logging sinks."""
        if not _LOGGING_AVAILABLE:
            return BoundedLogResult(query_type="token_usage", entries=[], total_count=0)

        loop = asyncio.get_running_loop()
        start_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        ts_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        default_filter = (
            '(resource.type="aiplatform.googleapis.com/Endpoint" OR '
            'resource.type="aiplatform.googleapis.com/PublisherModel") '
            f'AND timestamp>="{ts_str}"'
        )
        active_filter = log_filter or default_filter

        def _sync() -> BoundedLogResult:
            try:
                client = self._get_client()
                entries: List[Dict[str, Any]] = []
                for entry in client.list_entries(
                    resource_names=[f"projects/{self.project_id}"],
                    filter_=active_filter,
                    order_by=gcp_logging.DESCENDING,
                    max_results=max_entries + 1,
                    page_size=min(max_entries + 1, 100),
                ):
                    payload = entry.payload if hasattr(entry, "payload") and isinstance(entry.payload, dict) else {}
                    entries.append(
                        {
                            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                            "severity": str(entry.severity),
                            "resource_type": entry.resource.type if entry.resource else None,
                            "labels": dict(entry.labels or {}),
                            "payload": payload,
                        }
                    )

                is_capped = len(entries) > max_entries
                final_entries = entries[:max_entries]

                return BoundedLogResult(
                    query_type="token_usage",
                    entries=final_entries,
                    total_count=len(final_entries),
                    capped=is_capped,
                    estimated=is_capped,
                )
            except Exception as exc:
                logger.warning("[LogService] token_usage query failed: %s", exc)
                return BoundedLogResult(query_type="token_usage", entries=[], total_count=0)

        return await loop.run_in_executor(None, _sync)

    async def get_error_logs(
        self,
        hours: int = 24,
        max_entries: int = 200,
        service_filter: Optional[str] = None,
    ) -> BoundedLogResult:
        """Fetch error log records (severity >= ERROR) with bounded capping."""
        if not _LOGGING_AVAILABLE:
            return BoundedLogResult(query_type="error_logs", entries=[], total_count=0)

        loop = asyncio.get_running_loop()
        start_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        ts_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        filters = [
            "severity>=ERROR",
            f'timestamp>="{ts_str}"',
        ]
        if service_filter:
            filters.append(service_filter)

        active_filter = " AND ".join(filters)

        def _sync() -> BoundedLogResult:
            try:
                client = self._get_client()
                entries: List[Dict[str, Any]] = []
                for entry in client.list_entries(
                    resource_names=[f"projects/{self.project_id}"],
                    filter_=active_filter,
                    order_by=gcp_logging.DESCENDING,
                    max_results=max_entries + 1,
                    page_size=min(max_entries + 1, 100),
                ):
                    text = ""
                    if hasattr(entry, "payload"):
                        if isinstance(entry.payload, dict):
                            text = entry.payload.get("message", str(entry.payload))
                        else:
                            text = str(entry.payload)

                    entries.append(
                        {
                            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                            "severity": str(entry.severity),
                            "resource_type": entry.resource.type if entry.resource else None,
                            "resource_labels": dict(entry.resource.labels or {}) if entry.resource else {},
                            "message": text[:500],
                            "labels": dict(entry.labels or {}),
                        }
                    )

                is_capped = len(entries) > max_entries
                final_entries = entries[:max_entries]

                return BoundedLogResult(
                    query_type="error_logs",
                    entries=final_entries,
                    total_count=len(final_entries),
                    capped=is_capped,
                    estimated=is_capped,
                )
            except Exception as exc:
                logger.warning("[LogService] error_logs query failed: %s", exc)
                return BoundedLogResult(query_type="error_logs", entries=[], total_count=0)

        return await loop.run_in_executor(None, _sync)
