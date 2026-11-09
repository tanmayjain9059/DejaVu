from types import SimpleNamespace

from app.api.routes.public_workflow import _trusted_client_ip


def request(headers=None, client_host="10.0.0.4"):
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=client_host),
    )


def test_cloudflare_client_ip_is_validated_and_used():
    assert _trusted_client_ip(request({"cf-connecting-ip": "203.0.113.9"})) == "203.0.113.9"


def test_spoofable_forwarded_for_is_never_used():
    assert _trusted_client_ip(
        request({"x-forwarded-for": "198.51.100.99"})
    ) == "10.0.0.4"


def test_invalid_cloudflare_header_falls_back_to_socket_peer():
    assert _trusted_client_ip(
        request({"cf-connecting-ip": "not-an-ip", "x-forwarded-for": "198.51.100.99"})
    ) == "10.0.0.4"
