import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx2
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.cookies import CSRF_COOKIE
from tests.auth.fake_idp import FakeIdentityProvider

BASE_URL = "http://localhost:5173"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def new_client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url=BASE_URL, follow_redirects=False)


def start_sign_in(
    client: TestClient, idp: FakeIdentityProvider, *, return_to: str = "/"
) -> tuple[str, httpx2.Response]:
    start = client.get("/api/v1/auth/google/start", params={"return_to": return_to})
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return state, start


def sign_in(
    client: TestClient,
    idp: FakeIdentityProvider,
    *,
    subject: str,
    email: str,
    name: str | None = "Synthetic Person",
    return_to: str = "/",
    **overrides: Any,
) -> httpx2.Response:
    state, _ = start_sign_in(client, idp, return_to=return_to)
    code = idp.issue_code(state, subject=subject, email=email, name=name, **overrides)
    return client.get("/api/v1/auth/google/callback", params={"code": code, "state": state})


@dataclass
class Persona:
    client: TestClient
    user_id: uuid.UUID
    session_id: uuid.UUID
    label: str

    def request(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        headers = dict(kwargs.pop("headers", {}))
        if method.upper() not in SAFE_METHODS:
            headers.setdefault("X-CSRF-Token", self.client.cookies.get(CSRF_COOKIE) or "")
        return self.client.request(method, path, headers=headers, **kwargs)


def make_persona(app: FastAPI, idp: FakeIdentityProvider, label: str) -> Persona:
    client = new_client(app)
    response = sign_in(
        client,
        idp,
        subject=f"subject-{label}",
        email=f"persona-{label}@example.test",
        name=f"Persona {label.upper()}",
    )
    assert response.status_code == 302
    me = client.get("/api/v1/auth/me").json()
    sessions = client.get("/api/v1/auth/sessions").json()
    return Persona(client, uuid.UUID(me["id"]), uuid.UUID(sessions[0]["id"]), label)
