"""The explicit sandbox heartbeat must preserve failures and real deadlines."""
import asyncio

import pytest


def test_thread_results_and_exceptions_are_not_masked():
    async def scenario():
        assert await asyncio.to_thread(lambda: 7) == 7
        def fail():
            raise RuntimeError('expected worker failure')
        with pytest.raises(RuntimeError, match='expected worker failure'):
            await asyncio.to_thread(fail)
    asyncio.run(scenario())


def test_real_deadline_still_cancels_pending_work():
    async def scenario():
        cancelled = asyncio.Event()
        async def work():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(work(), timeout=0.02)
        assert cancelled.is_set()
    asyncio.run(scenario())
