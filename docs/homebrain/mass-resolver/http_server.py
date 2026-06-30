#!/usr/bin/env python3
"""HTTP server for resolver commands. Python 3.5 compatible."""
import json
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import command_result as cr


def make_handler(dispatch_fn, secret):
    """Create a BaseHTTPRequestHandler subclass for the given dispatch function and secret."""
    class ResolverHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            # Check path
            if self.path != "/command":
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                error_resp = cr.err("command", "", "not_found", "unknown path", "Not found.")
                self.wfile.write(json.dumps(error_resp).encode())
                return

            # Check secret if set
            if secret:
                key = self.headers.get("X-Resolver-Key") or ""
                if not hmac.compare_digest(key, secret):
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    error_resp = cr.err("command", "", "unauthorized", "bad key", "Unauthorized.")
                    self.wfile.write(json.dumps(error_resp).encode())
                    return

            # Read body
            content_length = self.headers.get("Content-Length")
            if content_length:
                content_length = int(content_length)
            else:
                content_length = 0

            body = self.rfile.read(content_length) if content_length > 0 else b""

            # Parse JSON and validate it is a dict
            try:
                data = json.loads(body.decode())
                if not isinstance(data, dict):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    error_resp = cr.err("command", "", "invalid_input", "malformed request body", "Bad request.")
                    self.wfile.write(json.dumps(error_resp).encode())
                    return
            except (ValueError, UnicodeDecodeError):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                error_resp = cr.err("command", "", "invalid_input", "malformed request body", "Bad request.")
                self.wfile.write(json.dumps(error_resp).encode())
                return

            # Validate intent
            intent = data.get("intent")
            if not (isinstance(intent, str) and intent.strip()):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                error_resp = cr.err("command", "", "invalid_input", "missing intent", "Bad request.")
                self.wfile.write(json.dumps(error_resp).encode())
                return

            # Get params
            params = data.get("params", {})

            # Call dispatch and send response with exception handling
            try:
                result = dispatch_fn(intent, params)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                error_resp = cr.err(str(intent) if isinstance(intent, str) else "command", "", "upstream_error", repr(e), "Sorry, something went wrong.")
                self.wfile.write(json.dumps(error_resp).encode())

        def log_message(self, format, *args):
            # Suppress default logging (prevent secret leaks)
            pass

    return ResolverHandler


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server."""
    daemon_threads = True


def serve_http(host, port, dispatch_fn, secret):
    """Start a threaded HTTP server on (host, port) with the given dispatch function and secret.

    Args:
        host: Bind address (e.g., "127.0.0.1")
        port: Bind port (0 for auto-assign)
        dispatch_fn: Function(intent, params) -> CommandResult dict
        secret: Secret string for X-Resolver-Key header (None to disable)

    Returns:
        ThreadedHTTPServer instance (call .serve_forever() to run, .shutdown() to stop)
    """
    handler = make_handler(dispatch_fn, secret)
    server = ThreadedHTTPServer((host, port), handler)
    return server
