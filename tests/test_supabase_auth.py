from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from fastapi import HTTPException

from app.services import supabase_auth
from app.api import dependencies as auth_dependencies
from app.core.database import SCHEMA_MIGRATIONS, _migration_add_supabase_identity, _migration_lock_down_supabase_data_api


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



def _run_supabase_profile(monkeypatch, identity, *, allowed_domains, office_emails, connection):
    @contextmanager
    def fake_connect_db():
        yield connection

    monkeypatch.setattr(auth_dependencies, "AUTH_PROVIDER", "supabase")
    monkeypatch.setattr(auth_dependencies, "ALLOWED_EMAIL_DOMAINS", set(allowed_domains))
    monkeypatch.setattr(auth_dependencies, "OFFICE_USER_EMAILS", set(office_emails))
    monkeypatch.setattr(auth_dependencies, "verify_supabase_access_token", lambda token: identity)
    monkeypatch.setattr(auth_dependencies, "connect_db", fake_connect_db)
    request = SimpleNamespace(session={})
    return asyncio.run(auth_dependencies.authenticated_user(request, authorization="Bearer test-token"))


def _identity_database():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            supabase_user_id TEXT
        )"""
    )
    connection.execute(
        "CREATE UNIQUE INDEX idx_users_supabase_user_id ON users(supabase_user_id) WHERE supabase_user_id IS NOT NULL"
    )
    return connection


def test_supabase_student_identity_is_rejected_without_provisioning(monkeypatch):
    connection = _identity_database()
    identity = {
        "id": "auth-student-1",
        "email": "student@college.edu",
        "user_metadata": {"display_name": "Student User", "role": "office"},
    }
    with pytest.raises(HTTPException) as error:
        _run_supabase_profile(
            monkeypatch, identity, allowed_domains={"college.edu"},
            office_emails=set(), connection=connection,
        )
    assert error.value.status_code == 403
    assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    connection.close()


def test_supabase_office_role_requires_exact_allowlist_and_can_be_revoked(monkeypatch):
    connection = _identity_database()
    identity = {
        "id": "auth-office-1",
        "email": "office@college.edu",
        "user_metadata": {"display_name": "Office User", "role": "student"},
    }
    user = _run_supabase_profile(
        monkeypatch, identity, allowed_domains={"college.edu"},
        office_emails={"office@college.edu"}, connection=connection,
    )
    assert user["role"] == "office"
    with pytest.raises(HTTPException) as revoked:
        _run_supabase_profile(
            monkeypatch, identity, allowed_domains={"college.edu"},
            office_emails=set(), connection=connection,
        )
    assert revoked.value.status_code == 403
    stored = connection.execute("SELECT role FROM users WHERE email=?", (identity["email"],)).fetchone()
    assert stored["role"] == "office"
    connection.close()


def test_supabase_provisioning_rejects_unapproved_email_domain(monkeypatch):
    connection = _identity_database()
    identity = {
        "id": "auth-outsider-1",
        "email": "outsider@example.net",
        "user_metadata": {"display_name": "Outsider"},
    }
    with pytest.raises(HTTPException) as error:
        _run_supabase_profile(
            monkeypatch, identity, allowed_domains={"college.edu"},
            office_emails=set(), connection=connection,
        )
    assert error.value.status_code == 403
    assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    connection.close()

def test_supabase_identity_migration_is_registered_and_idempotent():
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL)")
    _migration_add_supabase_identity(connection)
    _migration_add_supabase_identity(connection)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
    assert "supabase_user_id" in columns
    versions = [version for version, _, _ in SCHEMA_MIGRATIONS]
    assert versions[-2:] == [8, 9]
    _migration_lock_down_supabase_data_api(connection)
    connection.execute("INSERT INTO users(email, supabase_user_id) VALUES (?, ?)", ("one@example.edu", "auth-1"))
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO users(email, supabase_user_id) VALUES (?, ?)", ("two@example.edu", "auth-1"))
    connection.close()
