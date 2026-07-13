from worker.pool import run


async def test_batch_priority_jobs():
    assert await run(["x", "y", "z"]) == ["x", "y", "z"]
