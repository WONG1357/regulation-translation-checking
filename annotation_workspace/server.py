from __future__ import annotations

import json
import mimetypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
PDF_DIR = ROOT / "pdfs"
EXPORT_DIR = ROOT / "exports"
HOST = "127.0.0.1"
PORT = 8000


class AnnotationHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/pdfs":
            self._send_json(
                [
                    {"name": path.name, "url": f"/pdfs/{path.name}"}
                    for path in sorted(PDF_DIR.glob("*.pdf"))
                ]
            )
            return
        if parsed.path.startswith("/pdfs/"):
            requested = (PDF_DIR / unquote(parsed.path.removeprefix("/pdfs/"))).resolve()
            if PDF_DIR.resolve() not in requested.parents or not requested.is_file():
                self.send_error(404)
                return
            data = requested.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(requested.name)[0] or "application/pdf")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def _send_json(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    PDF_DIR.mkdir(exist_ok=True)
    EXPORT_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), AnnotationHandler)
    print(f"PDF Teaching Workspace: http://localhost:{PORT}")
    print(f"Optional local PDF folder: {PDF_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping annotation workspace.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
