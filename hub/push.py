"""Web Push without payload (RFC 8030 + VAPID, RFC 8292).

The push service only gets an empty "wake up" message. The service worker then fetches the alert text
from the hub over the private network, so message content never passes through Google or Apple.
Needs the `cryptography` package for the VAPID signature (ES256).
"""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Push:
    def __init__(self, state_dir, subject):
        self.dir = state_dir
        self.subject = subject
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.Lock()
        key_path = os.path.join(self.dir, "vapid.pem")
        if not os.path.exists(key_path):
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(pem)
        with open(key_path, "rb") as f:
            self.key = serialization.load_pem_private_key(f.read(), None)
        pub = self.key.public_key().public_bytes(serialization.Encoding.X962,
                                                 serialization.PublicFormat.UncompressedPoint)
        self.public_key = b64u(pub)
        self.subs_path = os.path.join(self.dir, "subscriptions.json")
        self.alerts_path = os.path.join(self.dir, "alerts.json")

    # ---------- storage ----------
    def _load(self, path, default):
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return default

    def _save(self, path, data):
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)

    def subscribe(self, sub, label=""):
        ep = sub.get("endpoint", "")
        if not ep.startswith("https://"):
            raise ValueError("bad endpoint")
        with self.lock:
            subs = [s for s in self._load(self.subs_path, []) if s["endpoint"] != ep]
            subs.append({"endpoint": ep, "label": label[:60], "added": int(time.time())})
            self._save(self.subs_path, subs)
        return len(subs)

    def unsubscribe(self, endpoint):
        with self.lock:
            subs = [s for s in self._load(self.subs_path, []) if s["endpoint"] != endpoint]
            self._save(self.subs_path, subs)

    def count(self):
        return len(self._load(self.subs_path, []))

    # ---------- alerts ----------
    def latest(self, limit=10):
        return self._load(self.alerts_path, {"items": []})["items"][-limit:]

    def publish(self, items):
        """items: dicts with a stable `id`. Only ids not seen before wake the phones."""
        with self.lock:
            st = self._load(self.alerts_path, {"seen": {}, "items": []})
            fresh = [i for i in items if i["id"] not in st["seen"]]
            now = int(time.time())
            for i in fresh:
                st["seen"][i["id"]] = now
                st["items"].append({**i, "ts": now})
            # resolved alerts (no longer reported) leave the list, so the phone stops showing them
            live = {i["id"] for i in items}
            st["items"] = [i for i in st["items"] if i["id"] in live][-30:]
            st["seen"] = {k: v for k, v in st["seen"].items() if now - v < 30 * 86400}
            self._save(self.alerts_path, st)
        if fresh:
            self.wake(urgent=any(i.get("urgent") for i in fresh))
        return fresh

    def wake(self, urgent=True):
        dead = []
        for s in self._load(self.subs_path, []):
            code = self._send(s["endpoint"], urgent)
            if code in (404, 410):
                dead.append(s["endpoint"])
        for ep in dead:
            self.unsubscribe(ep)

    def _jwt(self, aud):
        head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
        body = b64u(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": self.subject}).encode())
        sig = self.key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(sig)
        return f"{head}.{body}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"

    def _send(self, endpoint, urgent):
        u = urllib.parse.urlsplit(endpoint)
        req = urllib.request.Request(endpoint, data=b"", method="POST", headers={
            "TTL": "86400", "Urgency": "high" if urgent else "normal", "Content-Length": "0",
            "Authorization": f"vapid t={self._jwt(f'{u.scheme}://{u.netloc}')}, k={self.public_key}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except OSError:
            return 0
