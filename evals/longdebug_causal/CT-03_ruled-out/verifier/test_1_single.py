from worker.pool import run


async def test_priority_single():
    assert await run(["a", "b"]) == ["a", "b"]
