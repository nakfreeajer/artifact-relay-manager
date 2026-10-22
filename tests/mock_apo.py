"""Deterministic authenticated loopback receiver used only by offline tests/demo."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class SimulatedApo:
    """Small HTTP server with durable eventId dedupe and controllable failures."""

    def __init__(self, project_id, secret, receipt_path):
        self.project_id = project_id
        self.secret = secret
        self.receipt_path = Path(receipt_path)
        self.lock = threading.Lock()
        if self.receipt_path.exists():
            self.receipts = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        else:
            self.receipts = {"schemaVersion": 1, "receipts": {}}
        self.request_count = 0
        self.processed_count = len(self.receipts["receipts"])
        self.drop_after_accept = 0
        self.response_delay_seconds = 0.0
        self.request_received = threading.Event()
        self.mode = "normal"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_POST(self):
                with owner.lock:
                    owner.request_count += 1
                    owner.request_received.set()
                    mode = owner.mode
                    owner.mode = "normal"
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        body = self.rfile.read(length)
                        payload = json.loads(body.decode("utf-8"))
                    except Exception:
                        self.send_error(400)
                        return
                    if self.path != "/notify" or not isinstance(payload, dict):
                        self.send_error(404)
                        return
                    request_signature = self.headers.get("X-ARM-Request-Signature", "")
                    expected = hmac.new(owner.secret, body, hashlib.sha256).hexdigest()
                    if (not hmac.compare_digest(request_signature, expected)
                            or payload.get("projectId") != owner.project_id
                            or set(payload) != {"projectId", "eventType", "fileId", "providerVersion",
                                                "driveUrl", "eventId", "detectedAt"}
                            or payload.get("eventType") not in {"PROMPT_CHANGED", "REPORT_CHANGED"}
                            or not isinstance(payload.get("eventId"), str)
                            or not re.fullmatch(r"m03-[a-f0-9]{64}", payload["eventId"])
                            or not isinstance(payload.get("fileId"), str)
                            or not isinstance(payload.get("providerVersion"), str)
                            or not re.fullmatch(r"[0-9]+", payload["providerVersion"])
                            or not isinstance(payload.get("driveUrl"), str)
                            or not payload["driveUrl"].startswith("https://drive.google.com/")
                            or not isinstance(payload.get("detectedAt"), str)):
                        self.send_error(401)
                        return
                    event_id = payload["eventId"]
                    if mode == "unauthorized":
                        self.send_error(401)
                        return
                    if mode == "server_error":
                        self.send_error(503)
                        return
                    if mode == "redirect":
                        self.send_response(302)
                        self.send_header("Location", owner.url)
                        self.end_headers()
                        return
                    payload_hash = hashlib.sha256(_canonical(payload)).hexdigest()
                    existing = owner.receipts["receipts"].get(event_id)
                    if existing is not None and existing["payloadHash"] != payload_hash:
                        self.send_error(409)
                        return
                    if existing is None:
                        owner.receipts["receipts"][event_id] = {
                            "projectId": owner.project_id, "eventId": event_id,
                            "eventType": payload["eventType"], "fileId": payload["fileId"],
                            "payloadHash": payload_hash,
                        }
                        _atomic_json(owner.receipt_path, owner.receipts)
                        owner.processed_count += 1
                    if owner.drop_after_accept:
                        owner.drop_after_accept -= 1
                        self.close_connection = True
                        return
                    ack = {"projectId": owner.project_id, "eventId": event_id}
                    if mode == "wrong_event":
                        ack["eventId"] = "wrong-event"
                    elif mode == "wrong_project":
                        ack["projectId"] = "wrong-project"
                    ack_bytes = _canonical(ack)
                    signature = hmac.new(owner.secret, ack_bytes, hashlib.sha256).hexdigest()
                    if mode == "wrong_signature":
                        signature = "0" * 64
                    if mode == "missing_ack":
                        ack_bytes = b"{}"
                    if owner.response_delay_seconds:
                        time.sleep(owner.response_delay_seconds)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("X-ARM-Ack-Signature", signature)
                    self.send_header("Content-Length", str(len(ack_bytes)))
                    self.end_headers()
                    self.wfile.write(ack_bytes)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/notify"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError("simulated APO server did not stop")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
