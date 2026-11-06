#!/usr/bin/env python3
"""Diagnose GCP credentials and Cloud Monitoring access.

Usage:
    .venv/bin/python scripts/check_gcp.py

The script never prints secret values. It validates:
  1. GCP_PROJECT_ID format.
  2. Application Default Credentials / service-account key.
  3. Cloud Monitoring API access and IAM permissions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OK = "\033[92mOK\033[0m"
ERR = "\033[91mERROR\033[0m"
WARN = "\033[93mWARN\033[0m"


def line(status: str, message: str) -> None:
    print(f"[{status}] {message}")


def looks_like_wrong_project_id(value: str) -> str | None:
    """Return a human-readable reason when *value* is clearly not a project ID."""
    if not value:
        return "GCP_PROJECT_ID is empty."

    lowered = value.strip().lower()
    if lowered.endswith(".apps.googleusercontent.com"):
        return (
            "GCP_PROJECT_ID looks like an OAuth Client ID, not a project ID. "
            "Copy the Project ID from Google Cloud Console → project selector "
            "(e.g. 'my-project-123456')."
        )
    if lowered.startswith("aiza"):
        return "GCP_PROJECT_ID looks like an API key, not a project ID."
    if "@" in value:
        return "GCP_PROJECT_ID looks like an email address, not a project ID."
    if " " in value:
        return "GCP_PROJECT_ID contains spaces."
    return None


def check_project_id() -> str | None:
    project_id = os.getenv("GCP_PROJECT_ID", "").strip()
    problem = looks_like_wrong_project_id(project_id)
    if problem:
        line(ERR, problem)
        return None
    line(OK, f"GCP_PROJECT_ID = {project_id}")
    return project_id


def check_credentials():
    try:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError
    except ImportError:
        line(ERR, "google-auth is not installed. Run: pip install -r requirements.txt")
        return None

    key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if key_path:
        path = Path(key_path).expanduser()
        if not path.is_file():
            line(ERR, f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {path}")
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "type" not in data:
                line(WARN, "The service-account JSON has no 'type' field; it may be invalid.")
        except Exception as exc:
            line(ERR, f"Could not parse GOOGLE_APPLICATION_CREDENTIALS: {exc}")
            return None
        line(OK, f"Service-account key found: {path.name}")
    else:
        line(WARN, "GOOGLE_APPLICATION_CREDENTIALS is not set; trying Application Default Credentials (ADC).")

    try:
        credentials, detected_project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    except DefaultCredentialsError as exc:
        line(ERR, f"No GCP credentials found: {exc}")
        print()
        print("Set up credentials with one of these options:")
        print()
        print("  A) Local user (recommended for development):")
        print("       gcloud auth application-default login")
        print()
        print("  B) Service account key:")
        print("       export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json")
        print()
        return None
    except Exception as exc:
        line(ERR, f"Credential loading failed: {type(exc).__name__}: {exc}")
        return None

    line(OK, f"Credentials loaded: {type(credentials).__name__}")
    if detected_project:
        line(OK, f"Quota/detected project: {detected_project}")
    email = getattr(credentials, "service_account_email", None)
    if email:
        line(OK, f"Service account: {email}")
    return credentials


def check_monitoring_api(project_id: str, credentials) -> bool:
    try:
        from google.api_core.exceptions import (
            Forbidden,
            GoogleAPICallError,
            NotFound,
            PermissionDenied,
        )
        from google.cloud import monitoring_v3
    except ImportError:
        line(ERR, "google-cloud-monitoring is not installed. Run: pip install -r requirements.txt")
        return False

    try:
        client = monitoring_v3.MetricServiceClient(credentials=credentials)
        request = monitoring_v3.ListMetricDescriptorsRequest(
            name=f"projects/{project_id}",
            page_size=1,
        )
        next(iter(client.list_metric_descriptors(request=request, timeout=10)), None)
        line(OK, "Cloud Monitoring API is reachable and the project has metric descriptors.")
        return True
    except PermissionDenied as exc:
        line(ERR, f"Permission denied (403): {exc}")
        print("       Grant the identity roles/monitoring.viewer (and roles/logging.viewer).")
    except Forbidden as exc:
        line(ERR, f"Forbidden (403): {exc}")
    except NotFound as exc:
        line(ERR, f"Project or API not found (404): {exc}")
        print("       Check the project ID and enable the Cloud Monitoring API.")
    except GoogleAPICallError as exc:
        line(ERR, f"GCP API error: {type(exc).__name__}: {exc}")
    except Exception as exc:
        line(ERR, f"Monitoring check failed: {type(exc).__name__}: {exc}")
    return False


def main() -> int:
    print("GCP FinOps Observatory — GCP connectivity check\n")
    project_id = check_project_id()
    if not project_id:
        print("\nFix GCP_PROJECT_ID in .env, then run this script again.")
        return 1

    credentials = check_credentials()
    if not credentials:
        print("\nFix credentials, then run this script again.")
        return 1

    ok = check_monitoring_api(project_id, credentials)
    if not ok:
        print("\nAlso verify that these APIs are enabled on the project:")
        print("  - Cloud Monitoring API (monitoring.googleapis.com)")
        print("  - Cloud Logging API (logging.googleapis.com)")
        return 1

    print("\nAll checks passed. Restart the backend and the dashboard should show live GCP data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
