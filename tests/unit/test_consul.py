import base64
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.error import URLError

import pytest

import app.consul_agent as consul_agent
import app.consul_registration as consul_registration_module
import app.consul_request as consul_request_module
import app.main as main
from app.consul import ConsulConfigurationError, load_prefix
from app.consul_agent import deregister_service, register_service

PREFIX = "pdf-extractext/dev/persistence/"
TOKEN = "service-token"
REGISTER_PATH = "/v1/agent/service/register"


@contextmanager
def consul_server(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def json_handler(body: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return Handler


def register(address: str) -> None:
    register_service(
        address,
        TOKEN,
        service_id="persistence-1",
        service_name="persistence",
        service_address="persistence-1",
        service_port=8000,
        check_url="http://persistence-1:8000/readyz",
    )


def test_load_prefix_decodes_values_and_sends_token():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers["X-Consul-Token"] == TOKEN
            body = json.dumps(
                [
                    {
                        "Key": f"{PREFIX}MAX_TEXT_BODY_BYTES",
                        "Value": base64.b64encode(b"10485760").decode(),
                    }
                ]
            ).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    with consul_server(Handler) as address:
        values = load_prefix(address, TOKEN, PREFIX)

    assert values == {"MAX_TEXT_BODY_BYTES": "10485760"}


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[{}]",
        b"[null]",
        b"{}",
        b"[]",
        json.dumps([{"Key": f"{PREFIX}file", "Value": None}]).encode(),
        json.dumps([{"Key": f"{PREFIX}file", "Value": "%%%"}]).encode(),
        json.dumps(
            [
                {
                    "Key": f"{PREFIX}file",
                    "Value": base64.b64encode(b"\xff").decode(),
                }
            ]
        ).encode(),
    ],
    ids=[
        "invalid-json",
        "missing-key",
        "invalid-entry-type",
        "not-a-list",
        "empty-prefix",
        "null-value",
        "invalid-base64",
        "invalid-utf8",
    ],
)
def test_load_prefix_rejects_a_malformed_response(body):
    with (
        consul_server(json_handler(body)) as address,
        pytest.raises(ConsulConfigurationError),
    ):
        load_prefix(address, TOKEN, PREFIX)


def test_load_prefix_rejects_a_key_outside_the_prefix():
    body = json.dumps(
        [{"Key": "other/file", "Value": base64.b64encode(b"value").decode()}]
    ).encode()

    with (
        consul_server(json_handler(body)) as address,
        pytest.raises(ConsulConfigurationError, match="outside"),
    ):
        load_prefix(address, TOKEN, PREFIX)


def test_load_prefix_requires_a_non_empty_prefix():
    with pytest.raises(ConsulConfigurationError, match="CONSUL_KV_PREFIX"):
        load_prefix("http://127.0.0.1:1", TOKEN, "   ")


def test_service_registration_uses_agent_api_and_token():
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            paths.append(self.path)
            assert self.headers["X-Consul-Token"] == TOKEN
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    with consul_server(Handler) as address:
        register(address)
        deregister_service(address, TOKEN, "persistence-1")

    assert paths == [
        REGISTER_PATH,
        "/v1/agent/service/deregister/persistence-1",
    ]


def test_registration_retries_a_transient_server_error(monkeypatch):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            paths.append(self.path)
            status = 500 if len(paths) == 1 else 200
            self.send_response(status)
            self.end_headers()

        def log_message(self, *_):
            pass

    monkeypatch.setattr(consul_request_module, "sleep", lambda _: None)
    with consul_server(Handler) as address:
        register(address)

    assert paths == [REGISTER_PATH, REGISTER_PATH]


def test_registration_stops_after_three_transient_server_errors(monkeypatch):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            paths.append(self.path)
            self.send_response(500)
            self.end_headers()

        def log_message(self, *_):
            pass

    monkeypatch.setattr(consul_request_module, "sleep", lambda _: None)
    with (
        consul_server(Handler) as address,
        pytest.raises(ConsulConfigurationError, match="HTTP 500"),
    ):
        register(address)

    assert len(paths) == 3


def test_registration_does_not_retry_a_client_error(monkeypatch):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            paths.append(self.path)
            self.send_response(400)
            self.end_headers()

        def log_message(self, *_):
            pass

    monkeypatch.setattr(consul_request_module, "sleep", lambda _: None)
    with (
        consul_server(Handler) as address,
        pytest.raises(ConsulConfigurationError, match="HTTP 400"),
    ):
        register(address)

    assert len(paths) == 1


def test_registration_retries_a_connection_abort(monkeypatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b""

    def flaky_urlopen(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionAbortedError("connection aborted")
        return Response()

    monkeypatch.setattr(consul_request_module, "urlopen", flaky_urlopen)
    monkeypatch.setattr(consul_request_module, "sleep", lambda _: None)

    register_service(
        "http://consul.example",
        TOKEN,
        service_id="persistence-1",
        service_name="persistence",
        service_address="persistence-1",
        service_port=8000,
        check_url="http://persistence-1:8000/readyz",
    )

    assert len(attempts) == 2


def test_registration_wraps_a_persistent_network_error(monkeypatch):
    def broken_urlopen(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(consul_request_module, "urlopen", broken_urlopen)
    monkeypatch.setattr(consul_request_module, "sleep", lambda _: None)

    with pytest.raises(
        ConsulConfigurationError,
        match="unable to update Consul service registry",
    ):
        register_service(
            "http://consul.example",
            TOKEN,
            service_id="persistence-1",
            service_name="persistence",
            service_address="persistence-1",
            service_port=8000,
            check_url="http://persistence-1:8000/readyz",
        )


async def test_registration_runs_off_the_event_loop_thread(monkeypatch):
    observed = {}

    def fake_register(**_kwargs):
        observed["thread"] = threading.current_thread()

    monkeypatch.setattr(consul_registration_module, "register_service", fake_register)

    await consul_registration_module.register_service_off_event_loop({})

    assert observed["thread"] is not threading.main_thread()
