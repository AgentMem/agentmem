from worker.pool import run


async def test_priority_batch():
    assert await run(["x", "y", "z"]) == ["x", "y", "z"]
