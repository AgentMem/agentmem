from api import make_token


def login(user):
    return make_token(user)
