"""Loopback-only Google-authenticated proxy for the two private Cloud Run services.

No Google credential is stored in the browser and no key/public listener is used. The
complete user JWT is duplicated in a credential header because Cloud Run strips
    signatures from its own IAM header. The backend independently verifies the JWT.
"""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def cloud_value(*args: str) -> str:
    result = subprocess.run(["gcloud", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


class IdentityToken:
    def __init__(self, account: str):
        self.account, self.token, self.until = account, "", 0.0
        self.lock = threading.Lock()

    def get(self) -> str:
        with self.lock:
            if self.until > time.time():
                return self.token
            token = cloud_value("auth", "print-identity-token", "--account=" + self.account)
            part = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            if claims.get("email", "").lower() != self.account.lower() or claims.get("email_verified") is not True:
                raise RuntimeError("The local Google identity does not match the selected account")
            self.token, self.until = token, min(float(claims["exp"]) - 60, time.time() + 3000)
            return token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="oa-apmena-techsandbox-ap-dv")
    parser.add_argument("--region", default="europe-west1")
    parser.add_argument("--service", default="neo-feedback-ui")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--account", help="Defaults to the currently signed-in gcloud account")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged loopback port (1024–65535)")
    account = args.account or cloud_value("config", "get-value", "account")
    endpoint = cloud_value("run", "services", "describe", args.service, "--project=" + args.project,
                           "--region=" + args.region, "--format=value(status.url)")
    target = urlsplit(endpoint)
    if target.scheme != "https" or not target.hostname or not target.hostname.endswith(".run.app") or target.username or target.password:
        parser.error("The service did not return a valid Cloud Run HTTPS origin")
    identity = IdentityToken(account)
    identity.get()  # Fail before opening a listener if gcloud is not signed in.

    class Proxy(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass  # Never log tokens, query strings or feedback payloads.

        def forward(self):
            connection = None
            try:
                host = urlsplit("http://" + (self.headers.get("Host") or ""))
                origin = urlsplit(self.headers.get("Origin") or "")
                if (host.hostname not in {"localhost", "127.0.0.1"} or host.port != args.port or
                    (origin.netloc and (origin.scheme != "http" or origin.hostname not in {"localhost", "127.0.0.1"} or origin.port != args.port))):
                    self.send_error(403, "Only same-origin loopback browser requests are permitted")
                    return
                if not self.path.startswith("/") or self.path.startswith("//"):
                    raise ValueError("Invalid request path")
                size = int(self.headers.get("Content-Length") or 0)
                if not 0 <= size <= 2 * 1024 * 1024:
                    self.send_error(413, "Request is too large")
                    return
                token = identity.get()
                headers = {key: self.headers[key] for key in ("Accept", "Accept-Encoding", "Content-Type", "Cache-Control", "Origin", "User-Agent", "X-Feedback-Demo-Authorization") if key in self.headers}
                headers.update({"Authorization": "Bearer " + token, "X-Feedback-User-Authorization": "Bearer " + token})
                connection = http.client.HTTPSConnection(target.hostname, timeout=610)
                connection.request(self.command, self.path, body=self.rfile.read(size) if size else None, headers=headers)
                response = connection.getresponse()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {"connection", "transfer-encoding", "keep-alive", "server", "date"}:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    while chunk := response.read(65536):
                        self.wfile.write(chunk)
                self.close_connection = True
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception:
                self.send_error(502, "Private cloud proxy failed; check gcloud sign-in and IAM/application access. No request was replayed.")
                self.close_connection = True
            finally:
                if connection:
                    connection.close()

        do_GET = do_HEAD = do_POST = do_PATCH = do_OPTIONS = forward

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Proxy)
    print(f"Private NEO feedback: http://localhost:{args.port}", flush=True)
    print("Bound to 127.0.0.1 only. Ctrl+C closes the proxy; both cloud services remain IAM-private.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
