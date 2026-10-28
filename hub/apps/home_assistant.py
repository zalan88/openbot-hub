"""Home Assistant app for OpenBot Hub: cameras (live snapshots) and the state of the house.

Talks to the Home Assistant REST API with a long-lived token read from `token_file`. No model calls.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

OFF = ("unavailable", "unknown")


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.url = cfg["url"].rstrip("/")
        with open(cfg["token_file"]) as f:
            self.token = f.read().strip()
        self.only = cfg.get("cameras")  # optional list of entity ids
        self.hide = set(cfg.get("hide_cameras", []))
        self.width = int(cfg.get("snapshot_width", 960))
        self.watch = cfg.get("alert_cameras", [])  # cameras that should never be offline
        self.info = {"id": "home_assistant", "name": cfg.get("title", "Casa"), "icon": "home",
                     "description": cfg.get("description", "Câmeras e estado da casa")}
        self._down_since = {}

    def req(self, path, raw=False, timeout=10):
        r = urllib.request.Request(self.url + path, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            data = resp.read()
            return (data, resp.headers.get("Content-Type", "image/jpeg")) if raw else json.loads(data)

    def states(self):
        return self.req("/api/states")

    def cameras(self, states=None):
        cams = []
        for s in states or self.states():
            eid = s["entity_id"]
            if not eid.startswith("camera.") or (self.only and eid not in self.only) or eid in self.hide:
                continue
            cams.append({"entity": eid, "name": s["attributes"].get("friendly_name", eid)
                         .replace(" High resolution channel", ""), "state": s["state"],
                         "online": s["state"] not in OFF})
        cams.sort(key=lambda c: (not c["online"], c["name"]))
        return cams

    def status(self):
        try:
            cfg = self.req("/api/config")
            states = self.states()
        except (OSError, ValueError) as e:
            return {"online": False, "error": str(e)[:200]}
        off = {}
        for s in states:
            if s["state"] in OFF:
                d = s["entity_id"].split(".")[0]
                off[d] = off.get(d, 0) + 1
        return {"online": True, "version": cfg.get("version"), "location": cfg.get("location_name"),
                "entities": len(states), "unavailable": sum(off.values()),
                "unavailable_by_domain": sorted(off.items(), key=lambda kv: -kv[1])[:8],
                "cameras": self.cameras(states)}

    def snapshot(self, entity):
        if not entity.startswith("camera.") or (self.only and entity not in self.only):
            return 404, {"error": "unknown camera"}
        q = urllib.parse.urlencode({"width": self.width, "t": int(time.time())})
        try:
            data, ctype = self.req(f"/api/camera_proxy/{urllib.parse.quote(entity)}?{q}", raw=True, timeout=15)
        except urllib.error.HTTPError as e:
            return 502, {"error": f"camera {e.code}"}
        except OSError as e:
            return 502, {"error": str(e)[:200]}
        return 200, (data, ctype if ctype.startswith("image/") else "image/jpeg")

    def alerts(self):
        out = []
        try:
            states = self.states()
        except (OSError, ValueError):
            first = self._down_since.setdefault("__ha__", time.time())
            if time.time() - first > 120:
                out.append({"id": f"ha-down-{int(first)}", "title": "Home Assistant fora do ar",
                            "body": "O Hub não consegue falar com o Home Assistant há mais de 2 minutos.",
                            "url": "/#/home_assistant", "tag": "ha-down", "urgent": True})
            return out
        self._down_since.pop("__ha__", None)
        for c in self.cameras(states):
            if c["entity"] not in self.watch:
                continue
            if c["online"]:
                self._down_since.pop(c["entity"], None)
                continue
            first = self._down_since.setdefault(c["entity"], time.time())
            if time.time() - first > 300:
                out.append({"id": f"cam-off-{c['entity']}-{int(first)}", "title": f"Câmera offline: {c['name']}",
                            "body": "Sem imagem há mais de 5 minutos.", "url": "/#/home_assistant",
                            "tag": f"cam-{c['entity']}"})
        return out

    def handle(self, method, path, q, body):
        if method != "GET":
            return 404, {"error": "not found"}
        if path == "status":
            return 200, self.status()
        if path == "snapshot":
            return self.snapshot(q.get("entity", ""))
        return 404, {"error": "not found"}
