"""Client address extraction for deployments behind Render's edge proxy."""
from __future__ import annotations

import ipaddress
import os

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """Return the client IP without trusting arbitrary forwarded headers.

    Render appends the connecting peer to the right-hand end of
    X-Forwarded-For. Only trust that value when Render's runtime hostname
    variable is present; local/dev requests use the socket peer address.
    Uvicorn proxy-header rewriting is disabled in deployment commands.
    """
    peer = request.client.host if request.client else "unknown"
    if not os.getenv("RENDER_EXTERNAL_HOSTNAME"):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return peer
    candidate = forwarded.rsplit(",", 1)[-1].strip().strip('"')
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer
