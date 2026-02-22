# email_verifier.py
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("EMAIL_VERIFICATION_BASE_URL")
ADMIN_EMAIL = os.getenv("EMAIL_VERIFICATION_EMAIL")
ADMIN_PASSWORD = os.getenv("EMAIL_VERIFICATION_PASSWORD")

if not API_BASE_URL:
    raise RuntimeError("API_BASE_URL missing in .env")
if not ADMIN_EMAIL or not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_EMAIL / ADMIN_PASSWORD missing in .env")

LOGIN_URL = f"{API_BASE_URL}/api/auth/login"
VERIFY_URL = f"{API_BASE_URL}/api/email-verification/check"

_token = None
_token_expiry = 0  # unix timestamp


def _login() -> str:
    global _token, _token_expiry

    resp = requests.post(
        LOGIN_URL,
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        },
        timeout=10,
    )
    resp.raise_for_status()

    token = resp.json()["token"]["accessToken"]

    # token valid ~1 hour → refresh early
    _token = token
    _token_expiry = time.time() + 50 * 60

    return _token


def _get_token() -> str:
    if not _token or time.time() >= _token_expiry:
        return _login()
    return _token


def verify_email(email: str) -> dict | None:
    token = _get_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        VERIFY_URL,
        json={"email": email},
        headers=headers,
        timeout=10,
    )

    # token rejected once → refresh & retry ONCE
    if resp.status_code == 401:
        token = _login()
        headers["Authorization"] = f"Bearer {token}"

        resp = requests.post(
            VERIFY_URL,
            json={"email": email},
            headers=headers,
            timeout=10,
        )

    if resp.status_code != 200:
        return None

    return resp.json()
