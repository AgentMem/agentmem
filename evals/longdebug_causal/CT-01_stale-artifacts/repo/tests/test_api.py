from app.api import list_users, read_user


def test_list_users_returns_all():
    assert [u["id"] for u in list_users()] == [1, 2, 3]


def test_list_users_pagination():
    assert [u["id"] for u in list_users(limit=1)] == [1]
    assert [u["id"] for u in list_users(limit=1, offset=1)] == [2]


def test_read_user_email():
    assert read_user(1)["email"] == "ada@example.com"


def test_read_user_missing():
    assert read_user(999) is None
