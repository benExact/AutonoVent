"""The ITN gate tests. They stay on loopback and do not contact PayFast."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.edge.itn_gate import ITN_PATH, ItnGateError, request_is_itn, serve_itn_gate
from app.payments.payfast import ITN_PROXY_HEADER

TOKEN = "gate-token-value"
BODY = b"m_payment_id=AV-1&payment_status=COMPLETE&amount_gross=10.00&signature=abc"


class UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size)
        self.server.requests.append(
            {
                "path": self.path,
                "body": body,
                "token": self.headers.get(ITN_PROXY_HEADER),
                "client_ip": self.headers.get("CF-Connecting-IP"),
                "content_type": self.headers.get("Content-Type"),
            }
        )
        payload = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


@pytest.fixture
def gate():
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    upstream.requests = []
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    proxy = serve_itn_gate(
        proxy_token=TOKEN,
        upstream_host="127.0.0.1",
        upstream_port=upstream.server_address[1],
        bind_host="127.0.0.1",
        bind_port=0,
    )
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    try:
        yield proxy.server_address[1], upstream
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()
        proxy_thread.join(timeout=2)
        upstream_thread.join(timeout=2)


def _request(port: int, method: str, path: str, body: bytes = b"", headers: dict | None = None) -> tuple[int, bytes]:
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


def test_only_the_exact_notification_post_is_forwarded(gate) -> None:
    port, upstream = gate
    blocked = [
        ("GET", "/docs"),
        ("GET", "/redoc"),
        ("GET", "/openapi.json"),
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/health/ready"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/addresses/suggestions?q=test"),
        ("POST", "/api/v1/checkout/quotes"),
        ("POST", "/api/v1/checkout/orders"),
        ("GET", "/api/v1/products"),
        ("GET", "/api/v1/admin/readiness"),
        ("GET", "/api/v1/orders"),
        ("GET", ITN_PATH),
        ("PUT", ITN_PATH),
        ("POST", ITN_PATH + "?debug=1"),
        ("POST", "/api/v1/payments/payfast/itn/extra"),
    ]
    for method, path in blocked:
        status, _payload = _request(port, method, path, BODY)
        assert status == 404, path
    assert upstream.requests == []
    status, payload = _request(
        port,
        "POST",
        ITN_PATH,
        BODY,
        {"Content-Type": "application/x-www-form-urlencoded", "CF-Connecting-IP": "197.97.145.144", ITN_PROXY_HEADER: "client-supplied"},
    )
    assert status == 200
    assert json.loads(payload)["status"] == "ok"
    assert len(upstream.requests) == 1
    forwarded = upstream.requests[0]
    assert forwarded["path"] == ITN_PATH
    assert forwarded["body"] == BODY
    assert forwarded["token"] == TOKEN
    assert forwarded["client_ip"] == "197.97.145.144"
    assert forwarded["content_type"].startswith("application/x-www-form-urlencoded")


def test_a_spoofed_client_list_is_not_forwarded(gate) -> None:
    port, upstream = gate
    status, _payload = _request(
        port,
        "POST",
        ITN_PATH,
        BODY,
        {"Content-Type": "application/x-www-form-urlencoded", "CF-Connecting-IP": "197.97.145.144, 8.8.8.8"},
    )
    assert status == 200
    assert upstream.requests[0]["client_ip"] is None
    assert upstream.requests[0]["body"] == BODY


def test_the_gate_refuses_a_public_bind_or_a_missing_token() -> None:
    with pytest.raises(ItnGateError):
        serve_itn_gate(proxy_token=TOKEN, bind_host="0.0.0.0", bind_port=0)
    with pytest.raises(ItnGateError):
        serve_itn_gate(proxy_token="", bind_port=0)
    assert request_is_itn("POST", ITN_PATH, "")
    assert not request_is_itn("POST", "/docs", "")
