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
        self.auto_prefix = cfg.get("automation_id_prefix")  # automations shown with an on/off switch
        self.timeline = cfg.get("timeline_entities", [])

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

    def post(self, path, body):
        r = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                   headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status

    def automations(self):
        if not self.auto_prefix:
            return {"automations": []}
        out = []
        for s in self.states():
            a = s["attributes"]
            if s["entity_id"].startswith("automation.") and str(a.get("id", "")).startswith(self.auto_prefix):
                out.append({"entity": s["entity_id"], "name": a.get("friendly_name", "").replace("[Dev] ", ""),
                            "on": s["state"] == "on", "last": a.get("last_triggered")})
        return {"automations": sorted(out, key=lambda x: x["name"])}

    def events(self, hours=24):
        """Detections from Protect event entities (person, animal, sounds...) in the last hours."""
        if not self.timeline:
            return {"events": []}
        start = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - hours * 3600))
        q = urllib.parse.urlencode({"filter_entity_id": ",".join(self.timeline), "no_attributes": "false"})
        hist = self.req(f"/api/history/period/{urllib.parse.quote(start)}?{q}", timeout=20)
        names = {"person": "Pessoa", "animal": "Animal", "pet": "Animal", "vehicle": "Veículo", "car": "Carro",
                 "package": "Pacote", "face": "Rosto", "license_plate": "Placa", "baby_cry": "Choro de bebê",
                 "speaking": "Conversa", "bark": "Latido", "smoke": "Alarme de fumaça", "co": "Alarme de CO",
                 "glass_break": "Vidro quebrando", "siren": "Sirene", "car_alarm": "Alarme de carro",
                 "car_horn": "Buzina", "motion": "Movimento"}
        out = []
        suffix = {"_person_detected": "person", "_animal_detected": "animal", "_vehicle_detected": "vehicle",
                  "_baby_cry_detected": "baby_cry", "_speaking_detected": "speaking", "_motion": "motion"}
        drop = ("smart", "sound", "motion", "detection", "detected", "person", "animal", "vehicle", "baby", "cry",
                "speaking")
        for series in hist:
            for st in series:
                eid, attrs = st["entity_id"], st.get("attributes", {})
                cam = next((v for k, v in self.cfg.get("camera_labels", {}).items() if k in eid), None) or \
                    " ".join(w for w in attrs.get("friendly_name", eid).split(" ") if w.lower() not in drop)
                if eid.startswith("event."):
                    et = attrs.get("event_type")
                    if not et or st["state"] in OFF:
                        continue
                    out.append({"ts": st["state"], "camera": cam, "kind": et, "label": names.get(et, et)})
                elif st["state"] == "on":
                    et = next((v for k, v in suffix.items() if eid.endswith(k)), "motion")
                    out.append({"ts": st["last_changed"], "camera": cam, "kind": et, "label": names.get(et, et)})
        out.sort(key=lambda e: e["ts"], reverse=True)
        return {"events": out[:200]}

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

    def morning(self):
        """Once a day, from `hour`: a summary of the night (19h–now) as a normal alert. No model calls."""
        m = self.cfg.get("morning_summary")
        if not m:
            return []
        lt = time.localtime()
        day = time.strftime("%Y-%m-%d", lt)
        if lt.tm_hour < m.get("hour", 7) or lt.tm_hour >= m.get("until", 11):
            return []
        cached = getattr(self, "_morning", None)
        if cached and cached["day"] == day:
            return [cached["alert"]]
        night_h = lt.tm_hour + 5 + lt.tm_min / 60  # since 19h yesterday
        ev = self.events(hours=int(night_h) + 1)["events"]
        cutoff = time.time() - night_h * 3600
        from datetime import datetime
        ev = [e for e in ev if datetime.fromisoformat(e["ts"]).timestamp() >= cutoff]
        lines = []
        cry = sum(1 for e in ev if e["kind"] == "baby_cry")
        people = {}
        for e in ev:
            if e["kind"] in ("person", "animal", "vehicle", "speaking"):
                k = f"{e['label']} ({e['camera']})"
                people[k] = people.get(k, 0) + 1
        lines.append(f"Choro de bebê: {cry} vez(es)" if cry else "Sem choro detectado")
        if people:
            lines.append("Câmeras: " + ", ".join(f"{k} {v}x" for k, v in sorted(people.items(), key=lambda x: -x[1])[:4]))
        te = m.get("temp_entity")
        if te:
            try:
                start = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(cutoff))
                hist = self.req(f"/api/history/period/{urllib.parse.quote(start)}?filter_entity_id={te}&minimal_response", timeout=20)
                vals = [float(x["state"]) for x in (hist[0] if hist else []) if x["state"] not in OFF]
                if vals:
                    lines.append(f"Quarto: {min(vals):.1f} a {max(vals):.1f} °C")
            except (OSError, ValueError, IndexError):
                pass
        st = {s["entity_id"]: s for s in self.states()}
        off = [st[e]["attributes"].get("friendly_name", e) for e in m.get("watch_entities", []) if e in st and st[e]["state"] in OFF]
        if off:
            lines.append("Sem sinal: " + ", ".join(off))
        vac = st.get(m.get("vacuum", ""), {})
        if vac:
            lines.append("Robô: " + {"docked": "na base", "cleaning": "limpando", "error": "com erro",
                                     "returning": "voltando"}.get(vac.get("state"), str(vac.get("state"))))
        alert = {"id": f"resumo-{day}", "title": "☀️ Bom dia: como foi a noite", "body": " · ".join(lines),
                 "url": "/#/home_assistant/eventos", "tag": "resumo-manha"}
        self._morning = {"day": day, "alert": alert}
        return [alert]

    def alerts(self):
        out = list(self.morning())
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
        if method == "POST" and path == "automations/toggle":
            eid = (body or {}).get("entity", "")
            if eid not in [a["entity"] for a in self.automations()["automations"]]:
                return 400, {"error": "automação desconhecida"}
            svc = "turn_on" if (body or {}).get("on") else "turn_off"
            try:
                self.post(f"/api/services/automation/{svc}", {"entity_id": eid})
            except OSError as e:
                return 502, {"error": str(e)[:200]}
            return 200, {"ok": True}
        if method != "GET":
            return 404, {"error": "not found"}
        if path == "automations":
            return 200, self.automations()
        if path == "events":
            return 200, self.events(int(q.get("hours", 24)))
        if path == "status":
            return 200, self.status()
        if path == "snapshot":
            return self.snapshot(q.get("entity", ""))
        return 404, {"error": "not found"}
