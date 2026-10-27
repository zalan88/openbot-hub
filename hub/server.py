#!/usr/bin/python3 -I
"""OpenBot Hub: a small, installable web app (PWA) for the people who run an OpenBot server.

Standard library only. Apps live in hub/apps/<id>.py and expose `App(config)` with `info` and `handle()`.
Access control: only client IPs in `allow_cidrs` and not in `deny_ips` get in. Behind a reverse proxy on a
Unix socket, the proxy passes the client IP in `client_ip_header`; on TCP the peer address is used.
"""
import http.server
import importlib
import ipaddress
import json
import mimetypes
import os
import socketserver
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
CONFIG_PATH = os.environ.get("HUB_CONFIG", "/etc/openbot-hub/config.json")
sys.path.insert(0, ROOT)
from hub import icons  # noqa: E402

DEFAULTS = {
    "name": "Hub",
    "short_name": "Hub",
    "theme_color": "#111317",
    "listen": "127.0.0.1:8790",
    "client_ip_header": "X-Hub-Client-IP",
    "allow_cidrs": ["100.64.0.0/10", "fd7a:115c:a1e0::/48"],
    "deny_ips": [],
    "socket_group": "",
    "apps": {},
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    return cfg


CFG = load_config()
ALLOW = [ipaddress.ip_network(c) for c in CFG["allow_cidrs"]]
DENY = {ipaddress.ip_address(i) for i in CFG["deny_ips"]}
APPS = {}
for app_id, app_cfg in CFG["apps"].items():
    if app_cfg.get("enabled", True):
        mod = importlib.import_module(f"hub.apps.{app_id}")
        APPS[app_id] = mod.App(app_cfg)


def allowed(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr not in DENY and any(addr in n for n in ALLOW)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "OpenBotHub"
    sys_version = ""

    def address_string(self):
        return self.client_ip()

    def client_ip(self):
        if isinstance(self.client_address, tuple) and self.client_address:
            return self.client_address[0]
        return (self.headers.get(CFG["client_ip_header"]) or "").split(",")[0].strip()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.client_ip(), fmt % args))

    def send(self, status, body, ctype="application/json; charset=utf-8", cache="no-store"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                         "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def gate(self):
        if not allowed(self.client_ip()):
            self.send(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self):
        if not self.gate():
            return
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        if path.startswith("/api/"):
            return self.api("GET", path, urllib.parse.parse_qs(url.query), None)
        if path == "/manifest.webmanifest":
            return self.send(200, self.manifest(), "application/manifest+json")
        if path.startswith("/icons/"):
            data = icons.get(path[len("/icons/"):])
            if data is None:
                return self.send(404, {"error": "not found"})
            return self.send(200, data, "image/png", "public, max-age=86400")
        if path in ("/", "/index.html") or not os.path.splitext(path)[1]:
            path = "/index.html"
        full = os.path.realpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(WEB + os.sep) or not os.path.isfile(full):
            return self.send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        if path == "/index.html":
            data = data.replace(b"{{NAME}}", CFG["name"].encode())
        self.send(200, data, ctype, "no-cache")

    def do_POST(self):
        if not self.gate():
            return
        if self.headers.get("X-Hub") != "1":
            return self.send(400, {"error": "missing X-Hub header"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64 * 1024:
            return self.send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad json"})
        url = urllib.parse.urlsplit(self.path)
        self.api("POST", url.path, urllib.parse.parse_qs(url.query), body)

    def api(self, method, path, query, body):
        parts = path.strip("/").split("/")[1:]
        if parts == ["apps"]:
            return self.send(200, {"name": CFG["name"], "apps": [a.info for a in APPS.values()]})
        if not parts or parts[0] not in APPS:
            return self.send(404, {"error": "unknown app"})
        q = {k: v[0] for k, v in query.items()}
        try:
            status, payload = APPS[parts[0]].handle(method, "/".join(parts[1:]), q, body)
        except Exception as e:  # an app error must not take the hub down
            sys.stderr.write(f"app {parts[0]} error: {e!r}\n")
            status, payload = 500, {"error": "app error"}
        self.send(status, payload)

    def manifest(self):
        return {
            "name": CFG["name"], "short_name": CFG["short_name"], "id": "/", "start_url": "/", "scope": "/",
            "display": "standalone", "orientation": "portrait", "lang": "pt-BR",
            "theme_color": CFG["theme_color"], "background_color": CFG["theme_color"],
            "icons": [
                {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
                 "purpose": "maskable"},
            ],
        }


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class TCPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    listen = CFG["listen"]
    if listen.startswith("unix:"):
        sock = listen[5:]
        if os.path.exists(sock):
            os.remove(sock)
        srv = UnixServer(sock, Handler)
        os.chmod(sock, 0o660)
        if CFG.get("socket_group"):
            import grp
            os.chown(sock, -1, grp.getgrnam(CFG["socket_group"]).gr_gid)
    else:
        host, _, port = listen.rpartition(":")
        srv = TCPServer((host, int(port)), Handler)
    sys.stderr.write(f"hub on {listen} with apps {list(APPS)}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
