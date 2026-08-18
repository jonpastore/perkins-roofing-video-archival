"""Knowify browser OAuth helpers (Dynamic Client Registration + PKCE).

CompanyCam is an Application Key in companycam-pat — there is no user OAuth flow.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

KNOWIFY_AS = "https://developers-v2.knowify.com"
KNOWIFY_REG = KNOWIFY_AS + "/oauth/reg"
KNOWIFY_AUTH = KNOWIFY_AS + "/oauth/auth"
KNOWIFY_TOKEN = KNOWIFY_AS + "/oauth/token"
KNOWIFY_MCP = "https://assistant.knowify.com/api/v2/mcp"
KNOWIFY_SCOPES = (
    "openid profile offline_access invoices:read clients:read projects:read "
    "bills:read payments:read milestones:read items:read contracts:read "
    "documents:read vendors:read users:read"
)

def pkce() -> tuple[str, str]:
    import base64
    verifier = secrets.token_urlsafe(40)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def register_knowify_client(redirect_uri: str) -> str:
    body = json.dumps({
        "client_name": "Perkins Platform (Knowify reconnect)",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": KNOWIFY_SCOPES,
    }).encode()
    req = urllib.request.Request(
        KNOWIFY_REG, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    client_id = data.get("client_id") or ""
    if not client_id:
        raise RuntimeError("Knowify DCR returned no client_id")
    return client_id


def knowify_auth_url(*, client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    q = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": KNOWIFY_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": KNOWIFY_MCP,
    })
    return f"{KNOWIFY_AUTH}?{q}"


def exchange_knowify(*, code: str, client_id: str, redirect_uri: str, verifier: str) -> dict[str, Any]:
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": KNOWIFY_MCP,
    }).encode()
    req = urllib.request.Request(
        KNOWIFY_TOKEN, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def persist_knowify_mcp(tokens: dict[str, Any], client_id: str) -> None:
    from core.knowify.tokens import save_mcp_tokens  # noqa: PLC0415

    blob = {
        "clientId": client_id,
        "accessToken": tokens.get("access_token") or "",
        "refreshToken": tokens.get("refresh_token") or "",
        "expiresAt": int(time.time() * 1000) + int(tokens.get("expires_in") or 28800) * 1000,
        "scope": tokens.get("scope") or KNOWIFY_SCOPES,
    }
    if not blob["accessToken"] or not blob["refreshToken"]:
        raise RuntimeError("Knowify token response missing access or refresh token")
    save_mcp_tokens(blob)
