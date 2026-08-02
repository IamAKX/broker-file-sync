# api/notifications_api.py
from api.client import api_client
from api.endpoints import NOTIFICATIONS_EMAIL_SEND, NOTIFICATIONS_EMAIL_TEST


def send_email(subject: str, message: str) -> None:
    """Delivers to the logged-in user's own registered email — the backend
    resolves the recipient from the bearer token, not from this call."""
    api_client.post(NOTIFICATIONS_EMAIL_SEND, json_body={"subject": subject, "message": message})


def send_test_email(to_email: str, subject: str, message: str) -> None:
    api_client.post(
        NOTIFICATIONS_EMAIL_TEST,
        json_body={"to_email": to_email, "subject": subject, "message": message},
    )
