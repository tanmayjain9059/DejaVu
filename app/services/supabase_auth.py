"""Supabase Auth access-token verification for LostLink."""
from __future__ import annotations
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from fastapi import HTTPException
from app.core.config import SUPABASE_ANON_KEY, SUPABASE_URL, SUPABASE_REQUIRE_CONFIRMED_EMAIL

def verify_supabase_access_token(access_token: str) -> dict:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=503, detail="Supabase authentication is not configured.")
    if not access_token or len(access_token) > 16384:
        raise HTTPException(status_code=401, detail="Please sign in.")
    request = Request(
        SUPABASE_URL + "/auth/v1/user",
        headers={"apikey": SUPABASE_ANON_KEY, "Authorization": "Bearer " + access_token, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=6) as response:
            user = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise HTTPException(status_code=401, detail="Your sign-in session is invalid or expired.") from exc
        raise HTTPException(status_code=503, detail="Identity provider is temporarily unavailable.") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Unable to verify your sign-in session right now.") from exc
    user_id = str(user.get("id") or "").strip()
    email = str(user.get("email") or "").strip().lower()
    if not user_id or not email:
        raise HTTPException(status_code=401, detail="The identity provider returned an incomplete account.")
    if SUPABASE_REQUIRE_CONFIRMED_EMAIL and not (user.get("email_confirmed_at") or user.get("confirmed_at")):
        raise HTTPException(status_code=403, detail="Verify your email address before using LostLink.")
    return user
