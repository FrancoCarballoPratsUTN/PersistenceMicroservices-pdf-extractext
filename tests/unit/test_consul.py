import base64
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from app.consul import load_prefix
from app.consul_agent import deregister_service, register_service


def test_load_prefix_decodes_values_and_sends_token():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers["X-Consul-Token"] == "service-token"
            body = json.dumps(
                [
                    {
                        "Key": "pdf-extractext/dev/persistence/MAX_TEXT_BODY_BYTES",
                        "Value": base64.b64encode(b"10485760").decode(),
                    }
                ]
            ).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.handle_request, daemon=True).start()
    try:
        values = load_prefix(
            f"http://127.0.0.1:{server.server_port}",
            "service-token",
            "pdf-extractext/dev/persistence/",
        )
    finally:
        server.server_close()

    assert values == {"MAX_TEXT_BODY_BYTES": "10485760"}


def test_service_registration_uses_agent_api_and_token():
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            paths.append(self.path)
            assert self.headers["X-Consul-Token"] == "service-token"
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        address = f"http://127.0.0.1:{server.server_port}"
        register_service(
            address,
            "service-token",
            service_id="persistence-1",
            service_name="persistence",
            service_address="persistence-1",
            service_port=8000,
            check_url="http://persistence-1:8000/readyz",
        )
        deregister_service(address, "service-token", "persistence-1")
    finally:
        server.shutdown()
        server.server_close()

    assert paths == [
        "/v1/agent/service/register",
        "/v1/agent/service/deregister/persistence-1",
    ]
