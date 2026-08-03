# api/auth_api.py
from api.client import api_client
from api.endpoints import CHANGE_PASSWORD, LOGIN, LOGOUT, ME, SIGNUP, THEME


def login(email: str, password: str) -> dict:
    return api_client.post(LOGIN, json_body={"email": email, "password": password}, auth=False)


def signup(name: str, email: str, phone_number: str, password: str) -> dict:
    return api_client.post(
        SIGNUP,
        json_body={
            "name": name, "email": email, "phone_number": phone_number, "password": password,
        },
        auth=False,
    )


def logout(refresh_token: str) -> None:
    api_client.post(LOGOUT, json_body={"refresh_token": refresh_token}, auth=False)


def get_me() -> dict:
    return api_client.get(ME)


def update_profile(name: str, email: str, phone_number: str) -> dict:
    return api_client.patch(
        ME, json_body={"name": name, "email": email, "phone_number": phone_number},
    )


def change_password(current_password: str, new_password: str) -> None:
    api_client.post(
        CHANGE_PASSWORD,
        json_body={"current_password": current_password, "new_password": new_password},
    )


def get_theme() -> dict:
    return api_client.get(THEME)


def update_theme(theme: str) -> dict:
    return api_client.put(THEME, json_body={"theme": theme})
