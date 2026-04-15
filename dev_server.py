"""Local live server for the preliminary footing prototype."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from footing_prelim.calculations import design_rectangular_footing
from footing_prelim.models import FootingDesignInput


ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"


class PrototypeHandler(SimpleHTTPRequestHandler):
    """Serve the prototype UI and a small JSON API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        """Serve the UI and a small health endpoint."""

        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json({"status": "ok"})
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        """Handle calculation requests from the browser."""

        parsed = urlparse(self.path)
        if parsed.path != "/api/design":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
            design_input = build_design_input(payload)
            result = design_rectangular_footing(design_input)
        except ValueError as exc:
            self.send_json(
                {
                    "error": "INVALID_INPUT",
                    "message": str(exc),
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        except json.JSONDecodeError:
            self.send_json(
                {
                    "error": "INVALID_JSON",
                    "message": "Request body must be valid JSON.",
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        self.send_json(asdict(result))

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        """Write a JSON response."""

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_design_input(payload: dict) -> FootingDesignInput:
    """Create a typed input object from request JSON."""

    allowed_fields = {field.name for field in fields(FootingDesignInput)}
    cleaned_payload = {key: value for key, value in payload.items() if key in allowed_fields}

    # Keep the casting rules simple and explicit for early-stage auditing.
    for key, value in cleaned_payload.items():
        cleaned_payload[key] = float(value)

    return FootingDesignInput(**cleaned_payload)


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the local development server."""

    server = ThreadingHTTPServer((host, port), PrototypeHandler)
    print(f"Serving footing prototype at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
