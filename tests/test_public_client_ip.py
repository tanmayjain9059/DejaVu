from types import SimpleNamespace

from app.api.routes.public_workflow import _trusted_client_ip


def request(headers=None, client_host="10.0.0.4"):
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=client_host),
    )


def test_forged_cloudflare_header_cannot_change_rate_limit_identity():
    peer = _trusted_client_ip(request())
    assert peer == "10.0.0.4"
    assert _trusted_client_ip(request({"cf-connecting-ip": "203.0.113.9"})) == peer
    assert _trusted_client_ip(request({"cf-connecting-ip": "198.51.100.99"})) == peer


def test_forged_forwarded_for_cannot_change_rate_limit_identity():
    peer = _trusted_client_ip(request())
    assert _trusted_client_ip(
        request({"x-forwarded-for": "198.51.100.99"})
    ) == peer
    assert _trusted_client_ip(
        request({"cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "198.51.100.99"})
    ) == peer


def test_socket_peer_identifies_distinct_clients():
    assert _trusted_client_ip(request(client_host="10.0.0.4")) != _trusted_client_ip(
        request(client_host="10.0.0.5")
    )


def test_missing_socket_peer_uses_single_unknown_bucket():
    request_without_peer = request({"cf-connecting-ip": "203.0.113.9"})
    request_without_peer.client = None
    assert _trusted_client_ip(request_without_peer) == "unknown"
