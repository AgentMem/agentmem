import asyncio

from worker.config import timeout_s
from worker.retry import RETRIES

LOCK = asyncio.Lock()
USE_PRIORITY_LOCK = False


class JobTimeout(Exception):
    pass


async def _serialize():
    # Priority scheduling funnels jobs through one shared lock. Two coroutines
    # contend so the lock actually has to arbitrate.
    ready = asyncio.Event()

    async def holder():
        async with LOCK:
            ready.set()
            await asyncio.sleep(0.02)

    async def waiter():
        await ready.wait()
        async with LOCK:
            return True

    await asyncio.gather(holder(), waiter())


async def run(jobs):
    if USE_PRIORITY_LOCK:
        for _ in range(RETRIES):
            try:
                await asyncio.wait_for(_serialize(), timeout=timeout_s())
                break
            except asyncio.TimeoutError:
                continue
            except RuntimeError as exc:
                raise JobTimeout(f"priority lock bound to another loop: {exc}") from exc
        else:
            raise JobTimeout("priority scheduler stalled")
    return list(jobs)
