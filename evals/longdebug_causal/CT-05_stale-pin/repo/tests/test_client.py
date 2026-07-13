from svc.client import make_client


def test_client_builds():
    client = make_client()
    client.close()
