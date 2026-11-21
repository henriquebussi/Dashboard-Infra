"""Explicit test-only fallback for sandboxes that cannot wake selector loops."""
import asyncio
import math
import warnings

import pytest


def pytest_addoption(parser):
    parser.addoption('--asyncio-poll-interval', type=float, default=None,
                     help='Explicit sandbox fallback: schedule an asyncio heartbeat in seconds (0 < n <= 1).')


@pytest.fixture(scope='session', autouse=True)
def sandbox_event_loop_policy(request):
    interval = request.config.getoption('--asyncio-poll-interval')
    if interval is None:
        yield
        return
    if not math.isfinite(interval) or not 0 < interval <= 1:
        raise pytest.UsageError('--asyncio-poll-interval must be finite and in (0, 1]')
    # Policy APIs are deprecated in Python 3.14, but used by asyncio and AnyIO
    # in the supported interpreter here. No application or installed file edits.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        previous = asyncio.get_event_loop_policy()
        class Policy(asyncio.DefaultEventLoopPolicy):
            def new_event_loop(self):
                loop = asyncio.SelectorEventLoop()
                def heartbeat():
                    loop.call_later(interval, heartbeat)
                loop.call_later(interval, heartbeat)
                return loop
        asyncio.set_event_loop_policy(Policy())
    request.config.issue_config_time_warning(pytest.PytestWarning(
        f'Explicit sandbox asyncio heartbeat enabled ({interval}s); production scheduling is not validated.'), stacklevel=2)
    try:
        yield
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            asyncio.set_event_loop_policy(previous)

@pytest.fixture(autouse=True)
def isolated_dashboard_config(monkeypatch, tmp_path):
    for role, email, token in [("VIEW_ONLY", "viewer@example.com", "test-viewer"), ("INFRA_ADMIN", "admin@example.com", "test-admin")]:
        monkeypatch.setenv(f"DASHBOARD_{role}_EMAIL", email)
        monkeypatch.setenv(f"DASHBOARD_{role}_TOKEN", token)
    monkeypatch.setenv("DASHBOARD_STATE_DB", str(tmp_path / "state.db"))
