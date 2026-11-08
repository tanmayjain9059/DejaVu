import os
import unittest
from unittest.mock import patch

from starlette.requests import Request

from app.core.client_ip import get_client_ip


def request_with_headers(headers=None, peer="10.0.0.10"):
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": raw_headers,
        "client": (peer, 12345),
        "server": ("lostlink.example", 443),
    })


class ClientIpTests(unittest.TestCase):
    def test_local_requests_ignore_forged_forwarded_header(self):
        with patch.dict(os.environ, {}, clear=True):
            request = request_with_headers({"x-forwarded-for": "1.1.1.1"})
            self.assertEqual(get_client_ip(request), "10.0.0.10")

    def test_render_uses_rightmost_appended_address(self):
        with patch.dict(os.environ, {"RENDER_EXTERNAL_HOSTNAME": "lostlink-q8ft.onrender.com"}):
            request = request_with_headers({"x-forwarded-for": "1.1.1.1, 203.0.113.25"})
            self.assertEqual(get_client_ip(request), "203.0.113.25")

    def test_invalid_forwarded_value_falls_back_to_peer(self):
        with patch.dict(os.environ, {"RENDER_EXTERNAL_HOSTNAME": "lostlink-q8ft.onrender.com"}):
            request = request_with_headers({"x-forwarded-for": "forged, not-an-ip"})
            self.assertEqual(get_client_ip(request), "10.0.0.10")


if __name__ == "__main__":
    unittest.main()
