"""Classification must keep network failures distinct from remote access results."""

import json

import pytest
from google.api_core import exceptions

from scripts.gcp_diagnostics import classify_error


@pytest.mark.parametrize(
    "error,status",
    [
        (exceptions.ServiceUnavailable("Could not contact DNS servers"), "dns_error"),
        (exceptions.ServiceUnavailable("errors resolving monitoring.googleapis.com"), "dns_error"),
        (exceptions.ServiceUnavailable("upstream unavailable"), "api_unavailable"),
        (exceptions.PermissionDenied("permission denied"), "authorization_denied"),
        (exceptions.Unauthenticated("invalid credentials"), "authentication_failed"),
        (exceptions.ResourceExhausted("quota exceeded"), "quota_exceeded"),
        (exceptions.NotFound("project unavailable"), "not_found"),
    ],
)
def test_classifies_distinct_failure_layers(error, status):
    assert classify_error(error)["status"] == status


def test_service_disabled_is_not_classified_as_iam_denial():
    error = exceptions.PermissionDenied(
        "API disabled", errors=[{"reason": "SERVICE_DISABLED"}]
    )
    assert classify_error(error)["status"] == "api_disabled"


@pytest.mark.parametrize(
    "exception_type",
    [exceptions.PermissionDenied, exceptions.ServiceUnavailable, RuntimeError],
)
def test_raw_error_messages_are_never_exposed(exception_type):
    secret = "Bearer super-secret-token client_secret=private-value"
    result = classify_error(exception_type(secret))
    rendered = json.dumps(result)
    assert secret not in rendered
    assert "super-secret-token" not in rendered
    assert "private-value" not in rendered
