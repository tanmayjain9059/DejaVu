from __future__ import annotations

import json
import pytest
from fastapi import HTTPException

from app.services import supabase_auth


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_supabase_token_verification_returns_confirmed_identity(monkeypatch):
    monkeypatch.setattr(supabase_auth, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(supabase_auth, "SUPABASE_ANON_KEY", "public-key")
    monkeypatch.setattr(supabase_auth, "SUPABASE_REQUIRE_CONFIRMED_EMAIL", True)
    user = {
        "id": "e7a2e0d0-6a0f-4cc0-9c2f-12b3e6a0c1aa",
        "email": "student@college.edu",
        "email_confirmed_at": "2026-11-07T10:00:00Z",
        "user_metadata": {"display_name": "Student"},
    }

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://example.supabase.co/auth/v1/user"
        assert request.get_header("Authorization") == "Bearer access-token"
        assert request.get_header("Apikey") == "public-key"
        assert timeout == 6
        return FakeResponse(user)

    monkeypatch.setattr(supabase_auth, "urlopen", fake_urlopen)
    assert supabase_auth.verify_supabase_access_token("access-token") == user


def test_supabase_token_rejects_unconfirmed_email(monkeypatch):
    monkeypatch.setattr(supabase_auth, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(supabase_auth, "SUPABASE_ANON_KEY", "public-key")
    monkeypatch.setattr(supabase_auth, "SUPABASE_REQUIRE_CONFIRMED_EMAIL", True)
    monkeypatch.setattr(supabase_auth, "urlopen", lambda *args, **kwargs: FakeResponse({
        "id": "e7a2e0d0-6a0f-4cc0-9c2f-12b3e6a0c1aa",
        "email": "student@college.edu",
    }))
    with pytest.raises(HTTPException) as error:
        supabase_auth.verify_supabase_access_token("access-token")
    assert error.value.status_code == 403


def test_supabase_token_rejects_missing_configuration(monkeypatch):
    monkeypatch.setattr(supabase_auth, "SUPABASE_URL", "")
    monkeypatch.setattr(supabase_auth, "SUPABASE_ANON_KEY", "")
    with pytest.raises(HTTPException) as error:
        supabase_auth.verify_supabase_access_token("access-token")
    assert error.value.status_code == 503


def test_supabase_token_rejects_invalid_identity(monkeypatch):
    monkeypatch.setattr(supabase_auth, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(supabase_auth, "SUPABASE_ANON_KEY", "public-key")
    monkeypatch.setattr(supabase_auth, "SUPABASE_REQUIRE_CONFIRMED_EMAIL", False)
    monkeypatch.setattr(supabase_auth, "urlopen", lambda *args, **kwargs: FakeResponse({"id": "", "email": ""}))
    with pytest.raises(HTTPException) as error:
        supabase_auth.verify_supabase_access_token("access-token")
    assert error.value.status_code == 401
