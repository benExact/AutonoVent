"""Localhost gate for one PayFast sandbox notification request.

The gate forwards only POST /api/v1/payments/payfast/itn. Every other path and
method stops here. The raw body is copied unchanged so PayFast's signature still
matches. A client-supplied proxy token is removed and replaced by this process.
"""

from __future__ import annotations

import http.client
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from app.payments.payfast import ITN_PROXY_HEADER

ITN_PATH = "/api/v1/payments/payfast/itn"
MAX_BODY_BYTES = 65536


class ItnGateError(Exception):
    """The gate cannot be started with this bind address or token."""


def request_is_itn(method: str, path: str, query: str) -> bool:
    return method.upper() == "POST" and path == ITN_PATH and query == ""


def serve_itn_gate(
    *,
    proxy_token: str,
    upstream_host: str = "127.0.0.1",
    upstream_port: int = 8001,
    bind_host: str = "127.0.0.1",
    bind_port: int = 8002,
) -> ThreadingHTTPServer:
    if bind_host not in {"127.0.0.1", "::1"}:
        raise ItnGateError("The ITN gate can listen only on the loopback address.")
    if upstream_host not in {"127.0.0.1", "::1"}:
        raise ItnGateError("The ITN gate can forward only to the loopback API.")
    if not proxy_token:
        raise ItnGateError("The ITN gate needs a proxy token.")
    handler = _handler(proxy_token=proxy_token, upstream_host=upstream_host, upstream_port=upstream_port)
    return ThreadingHTTPServer((bind_host, bind_port), handler)


def _handler(*, proxy_token: str, upstream_host: str, upstream_port: int) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle_one_request(self) -> None:
            try:
                self.raw_requestline = self.rfile.readline(65537)
                if not self.raw_requestline:
                    self.close_connection = True
                    return
                if not self.parse_request():
                    return
                self._dispatch()
            except (ConnectionError, TimeoutError):
                self.close_connection = True

        def _dispatch(self) -> None:
            target = urlsplit(self.path)
            if not request_is_itn(self.command, target.path, target.query):
                self._reject()
                return
            length = self.headers.get("Content-Length")
            if self.headers.get("Transfer-Encoding"):
                self._reject()
                return
            try:
                size = int(length or "0")
            except ValueError:
                self._reject()
                return
            if size < 0 or size > MAX_BODY_BYTES:
                self._reject()
                return
            body = self.rfile.read(size)
            status, response_body, content_type = _forward(
                host=upstream_host,
                port=upstream_port,
                body=body,
                content_type=self.headers.get("Content-Type", "application/x-www-form-urlencoded"),
                client_ip=self.headers.get("CF-Connecting-IP", ""),
                proxy_token=proxy_token,
            )
            self._send(status, response_body, content_type)

        def _reject(self) -> None:
            self.close_connection = True
            length = self.headers.get("Content-Length")
            try:
                size = int(length or "0")
            except ValueError:
                size = 0
            if 0 < size <= MAX_BODY_BYTES and not self.headers.get("Transfer-Encoding"):
                self.rfile.read(size)
            self._send(404, b"", "text/plain")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def _single_ip(value: str) -> str:
    candidate = value.strip()
    if not candidate or candidate != value or any(character.isspace() for character in candidate):
        return ""
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return ""
    return candidate


def _forward(
    *,
    host: str,
    port: int,
    body: bytes,
    content_type: str,
    client_ip: str,
    proxy_token: str,
) -> tuple[int, bytes, str]:
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        ITN_PROXY_HEADER: proxy_token,
        "Connection": "close",
    }
    forwarded_ip = _single_ip(client_ip)
    if forwarded_ip:
        headers["CF-Connecting-IP"] = forwarded_ip
    connection = http.client.HTTPConnection(host, port, timeout=20)
    try:
        connection.request("POST", ITN_PATH, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read(MAX_BODY_BYTES)
        media = response.getheader("Content-Type") or "application/json"
        return response.status, payload, media.split(";", 1)[0]
    except (http.client.HTTPException, OSError, TimeoutError):
        return 503, b"", "text/plain"
    finally:
        connection.close()
