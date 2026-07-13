from worker.pool import run


async def test_single_priority_jobs():
    assert await run(["a", "b"]) == ["a", "b"]
