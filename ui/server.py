#!/usr/bin/env python3
"""Local ShruTea UI server: upload a WAV and return real drift.py results."""

from __future__ import annotations

import cgi
import json
import subprocess
import sys
import tempfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


UI_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = UI_DIRECTORY.parent
DRIFT_SCRIPT = REPOSITORY_ROOT / "drift.py"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class ShruTeaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIRECTORY), **kwargs)

    def send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Choose a WAV file smaller than 100 MB."})
            return
        if not self.headers.get_content_type().startswith("multipart/"):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Expected a multipart WAV upload."})
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"], "CONTENT_LENGTH": str(content_length)},
        )
        upload = form["audio"] if "audio" in form else None
        if upload is None or not getattr(upload, "file", None) or not str(upload.filename).lower().endswith(".wav"):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "ShruTea currently accepts rendered WAV files only."})
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(upload.file.read())
        try:
            completed = subprocess.run(
                [sys.executable, str(DRIFT_SCRIPT), str(temporary_path)],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode:
                self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": completed.stderr.strip() or "drift.py failed."})
                return
            results = json.loads(completed.stdout)
            if not isinstance(results, list):
                raise ValueError("drift.py did not return a JSON array")
            self.send_json(HTTPStatus.OK, {"results": results})
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Analysis failed: {error}"})
        finally:
            temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    print("ShruTea UI running at http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), ShruTeaHandler).serve_forever()
