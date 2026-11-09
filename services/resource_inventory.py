"""GCP FinOps Observatory - Resource Inventory Extraction Service.

Derives managed GCP resource inventory dynamically from Cloud Monitoring
time-series metric labels and Cloud Logging event metadata.

Adheres strictly to `roles/monitoring.viewer` and `roles/logging.viewer` permissions:
  - Zero calls to Admin APIs (Compute Admin, SQL Admin, Storage Admin).
  - Inspects `resource.labels` on time-series descriptors and data points.
  - Maintains in-memory / cache-backed discovered inventory catalog.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from schemas import Environment, GCPService, GcpResourceMetadata

logger = logging.getLogger("gcp_observatory.resource_inventory")


class ResourceInventoryService:
    """Extracts and catalogs discovered GCP resources from metric telemetry."""

    def __init__(self) -> None:
        self._discovered_resources: Dict[str, GcpResourceMetadata] = {}

    def record_series_labels(
        self,
        category: str,
        metric_type: str,
        labels: Dict[str, str],
        env: Environment = Environment.PROD,
    ) -> Optional[GcpResourceMetadata]:
        """Inspect a metric's labels and extract any identifiable GCP resource."""
        if not labels:
            return None

        # 1. Cloud SQL
        if "database_id" in labels:
            raw_id = labels["database_id"]
            name = raw_id.split(":")[-1] if ":" in raw_id else raw_id
            region = labels.get("region", "us-central1")
            key = f"sql:{name}"
            existing = self._discovered_resources.get(key)
            if existing:
                existing.metric_count += 1
                return existing
            meta = GcpResourceMetadata(
                name=name,
                env=env,
                service=GCPService.CLOUD_SQL,
                region=region,
                resource_type="Database",
                labels=labels,
                metric_count=1,
            )
            self._discovered_resources[key] = meta
            return meta

        # 2. Compute Engine VMs
        if "instance_id" in labels or "instance_name" in labels:
            name = labels.get("instance_name") or labels.get("instance_id", "unknown-vm")
            zone = labels.get("zone", "us-central1-a")
            region = "-".join(zone.split("-")[:2]) if "-" in zone else zone
            key = f"compute:{name}"
            existing = self._discovered_resources.get(key)
            if existing:
                existing.metric_count += 1
                return existing
            meta = GcpResourceMetadata(
                name=name,
                env=env,
                service=GCPService.COMPUTE_ENGINE,
                region=region,
                resource_type="Cloud",
                labels=labels,
                metric_count=1,
            )
            self._discovered_resources[key] = meta
            return meta

        # 3. Cloud Storage Buckets
        if "bucket_name" in labels:
            name = labels["bucket_name"]
            location = labels.get("location", "US")
            key = f"gcs:{name}"
            existing = self._discovered_resources.get(key)
            if existing:
                existing.metric_count += 1
                return existing
            meta = GcpResourceMetadata(
                name=name,
                env=env,
                service=GCPService.CLOUD_STORAGE,
                region=location,
                resource_type="Storage",
                labels=labels,
                metric_count=1,
            )
            self._discovered_resources[key] = meta
            return meta

        # 4. BigQuery Datasets or Tables
        if "dataset_id" in labels or "table_id" in labels:
            name = labels.get("table_id") or labels.get("dataset_id", "bq-analytics")
            region = labels.get("project_id", "US")
            key = f"bq:{name}"
            existing = self._discovered_resources.get(key)
            if existing:
                existing.metric_count += 1
                return existing
            meta = GcpResourceMetadata(
                name=name,
                env=env,
                service=GCPService.BIGQUERY,
                region=region,
                resource_type="Processing",
                labels=labels,
                metric_count=1,
            )
            self._discovered_resources[key] = meta
            return meta

        # 5. Vertex AI Endpoints
        if "endpoint_id" in labels or "model_id" in labels:
            name = labels.get("model_id") or labels.get("endpoint_id", "vertex-endpoint")
            region = labels.get("location", "us-central1")
            key = f"ai:{name}"
            existing = self._discovered_resources.get(key)
            if existing:
                existing.metric_count += 1
                return existing
            meta = GcpResourceMetadata(
                name=name,
                env=env,
                service=GCPService.VERTEX_AI,
                region=region,
                resource_type="Token Usage",
                labels=labels,
                metric_count=1,
            )
            self._discovered_resources[key] = meta
            return meta

        return None

    def get_resources(
        self,
        env: Optional[Environment] = None,
        service: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[GcpResourceMetadata]:
        """Return list of discovered GCP resources matching filter criteria."""
        results: List[GcpResourceMetadata] = []
        term = search.strip().lower() if search else None

        for item in self._discovered_resources.values():
            if env and item.env != env:
                continue
            if service and service != "All services" and service != "Todos os serviços":
                svc_val = item.service.value if hasattr(item.service, "value") else str(item.service)
                if svc_val.lower() != service.lower():
                    continue
            if term:
                searchable = f"{item.name} {item.region} {item.resource_type}".lower()
                if term not in searchable:
                    continue
            results.append(item)

        return sorted(results, key=lambda r: (r.resource_type, r.name))

    def clear(self) -> None:
        """Clear the discovered resource inventory."""
        self._discovered_resources.clear()


resource_inventory = ResourceInventoryService()
