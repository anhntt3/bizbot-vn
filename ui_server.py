"""Simple proxy server: serves chat_ui.html and proxies /invocations to the agent.

Target agent URL is taken from the AGENT_URL env var, falling back to the deployed
AgentBase Runtime cloud endpoint. Set AGENT_URL=http://localhost:8080 to use the local agent.
"""
import json
import os
import ssl
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

AGENT_URL = os.environ.get(
    "AGENT_URL",
    "https://endpoint-8836972f-8e1f-46ac-870b-006e44f01c30.agentbase-runtime.aiplatform.vngcloud.vn",
).rstrip("/")

# Build an SSL context that trusts the certifi CA bundle, so HTTPS requests to the
# cloud endpoint verify correctly (Python's default store may not include the chain).
try:
    import certifi

    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access logs

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/chat_ui.html"):
            with open("chat_ui.html", "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.send_cors()
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/invocations":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            # Forward all relevant headers to agent
            forward_headers = {
                "Content-Type": "application/json",
                "X-GreenNode-AgentBase-User-Id": self.headers.get(
                    "X-GreenNode-AgentBase-User-Id", "analyst-1"
                ),
                "X-GreenNode-AgentBase-Session-Id": self.headers.get(
                    "X-GreenNode-AgentBase-Session-Id", "test-session-ui"
                ),
            }
            req = urllib.request.Request(
                AGENT_URL + "/invocations",
                data=body,
                headers=forward_headers,
                method="POST",
            )
            try:
                ctx = SSL_CTX if AGENT_URL.startswith("https") else None
                with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                    result = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(result)
            except Exception as e:
                error = json.dumps({"status": "error", "error": str(e)}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(error)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 3001), Handler)
    print("UI proxy running on http://localhost:3001")
    server.serve_forever()
