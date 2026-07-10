# api/auth_api.py
from api.client import api_client
from api.endpoints import LOGIN, LOGOUT, SIGNUP


def login(email: str, password: str) -> dict:
    return api_client.post(LOGIN, json_body={"email": email, "password": password}, auth=False)


def signup(name: str, email: str, password: str) -> dict:
    return api_client.post(
        SIGNUP,
        json_body={"name": name, "email": email, "password": password},
        auth=False,
    )


def logout(refresh_token: str) -> None:
    api_client.post(LOGOUT, json_body={"refresh_token": refresh_token}, auth=False)
