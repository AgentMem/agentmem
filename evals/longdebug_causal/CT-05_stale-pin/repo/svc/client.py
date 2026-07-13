import httpx


def make_client() -> httpx.Client:
    # No proxy configured. The keyword pins us to a specific httpx era.
    return httpx.Client(proxies=None)
