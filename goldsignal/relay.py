import argparse
import base64
import json
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ORIGIN = os.getenv("GOLDSIGNAL_API", "http://127.0.0.1:8011")
ROUTES = {("GET", "/api/dashboard"), ("GET", "/api/performance"), ("GET", "/api/sessions"),
          ("POST", "/api/lot-size"),
          ("GET", "/api/pnl"), ("PUT", "/api/pnl"), ("DELETE", "/api/pnl"),
          ("GET", "/api/strategy-b/config"), ("PUT", "/api/admin/strategy-b/config"),
          ("GET", "/api/admin/telegram"), ("PUT", "/api/admin/telegram"), ("POST", "/api/admin/telegram/test"),
          ("GET", "/api/viewer-profile"), ("PUT", "/api/viewer-profile"),
          ("POST", "/api/push/status"), ("POST", "/api/push/test"),
          ("PUT", "/api/push"), ("DELETE", "/api/push"), ("GET", "/api/auth/session"),
          ("DELETE", "/api/auth/session"), ("POST", "/api/auth/admin"), ("POST", "/api/auth/viewer"),
          ("GET", "/api/admin/settings"), ("POST", "/api/admin/keys"), ("PUT", "/api/admin/keys"), ("DELETE", "/api/admin/keys"),
          ("PUT", "/api/admin/gemini"), ("GET", "/api/admin/chat"), ("POST", "/api/admin/chat"),
          ("PUT", "/api/admin/pause"), ("GET", "/api/admin/errors"), ("DELETE", "/api/admin/errors"),
          ("GET", "/api/admin/performance"), ("POST", "/api/admin/performance/reset"),
          ("GET", "/api/admin/workers"),
          ("POST", "/api/entry-open")}


def encode(data):
    return base64.b64encode(data).decode()


def generate(path):
    key = Ed25519PrivateKey.generate()
    with path.open("xb") as file:
        file.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    print(encode(key.public_key().public_bytes(serialization.Encoding.DER,
                                              serialization.PublicFormat.SubjectPublicKeyInfo)))


def forward(client, request):
    route = urlsplit(request["path"])
    method = request["method"]
    if route.scheme or route.netloc or (method, route.path) not in ROUTES:
        return {"id": request["id"], "status": 404, "body": '{"detail":"Not found"}'}
    try:
        response = client.request(method, ORIGIN + request["path"], content=request["body"], headers={
            "Cookie": request["cookie"], "Content-Type": "application/json",
        })
        return {"id": request["id"], "status": response.status_code, "body": response.text,
                "cookie": response.headers.get("set-cookie")}
    except httpx.HTTPError:
        return {"id": request["id"], "status": 503, "body": '{"detail":"Local Goldsignal API is unavailable"}'}


def run(url, path):
    parsed = urlsplit(url)
    if parsed.scheme != "https" and parsed.hostname != "127.0.0.1":
        raise ValueError("Relay URL must use HTTPS")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    result = {}
    with httpx.Client(timeout=5, trust_env=False) as relay, httpx.Client(timeout=4, trust_env=False) as local:
        while True:
            stamp, nonce = str(time.time_ns() // 1_000_000), secrets.token_hex(16)
            body = json.dumps(result).encode()
            signature = key.sign(f"{stamp}.{nonce}.".encode() + body)
            try:
                response = relay.post(url.rstrip("/") + "/_relay/poll", content=body, headers={
                    "X-Relay-Time": stamp, "X-Relay-Nonce": nonce, "X-Relay-Signature": encode(signature),
                })
                response.raise_for_status()
                request = response.json()
                result = forward(local, request) if request else {}
                if not request:
                    time.sleep(0.6)
            except (httpx.HTTPError, ValueError) as exc:
                logging.warning("Ryaze relay unavailable: %s", exc)
                time.sleep(3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("key", type=Path)
    parser.add_argument("--url")
    options = parser.parse_args()
    generate(options.key) if options.url is None else run(options.url, options.key)
