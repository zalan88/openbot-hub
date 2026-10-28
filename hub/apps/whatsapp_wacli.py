"""WhatsApp (wacli) app for OpenBot Hub.

Reads the wacli store read-only (wacli.db) and, when a gate is configured, its allowlist, blocklist,
requests and log. Changes go through the gate's `admin` command, never by writing files here.
No model calls: every view is built from local data, so it costs no tokens.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import time
from zoneinfo import ZoneInfo


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.store = cfg["store_dir"]
        self.state = cfg.get("gate_state_dir")
        self.gate_cmd = cfg.get("gate_cmd")
        self.wacli = cfg.get("wacli", "wacli")
        self.units = cfg.get("units", [])
        self.tz = ZoneInfo(cfg.get("timezone", "UTC"))
        self.owner = set(cfg.get("owner_numbers", []))
        self.info = {"id": "whatsapp_wacli", "name": cfg.get("title", "WhatsApp"), "icon": "chat",
                     "description": cfg.get("description", "Allowlist, conversas e status do wacli"),
                     "gate": bool(self.state),
                     "roles": cfg.get("roles", [["personal", "Pessoal"], ["business", "Negócio"]])}

    # ---------- dados ----------
    def db(self):
        con = sqlite3.connect(f"file:{self.store}/wacli.db?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        return con

    def jfile(self, name, default):
        if not self.state:
            return default
        try:
            with open(os.path.join(self.state, name)) as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return default

    def when(self, ts):
        return dt.datetime.fromtimestamp(ts, self.tz).strftime("%d/%m %H:%M") if ts else ""

    @staticmethod
    def num_of(jid):
        user, _, server = (jid or "").partition("@")
        return user.split(":")[0] if server == "s.whatsapp.net" else ""

    def names(self, con):
        out = {}
        for r in con.execute("SELECT jid, COALESCE(NULLIF(full_name,''),NULLIF(business_name,''),"
                             "NULLIF(push_name,''),'') n FROM contacts"):
            n = self.num_of(r["jid"])
            if n and r["n"]:
                out[n] = r["n"]
        return out

    # ---------- views ----------
    def status(self):
        units = {}
        for u in self.units:
            p = subprocess.run(["systemctl", "is-active", u], capture_output=True, text=True)
            units[u] = p.stdout.strip() or "unknown"
        doc = {}
        try:
            p = subprocess.run([self.wacli, "--store", self.store, "--read-only", "--json", "doctor"],
                               capture_output=True, text=True, timeout=20)
            doc = (json.loads(p.stdout or "{}").get("data") or {})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        con = self.db()
        last_in = con.execute("SELECT MAX(ts) FROM messages WHERE from_me=0").fetchone()[0]
        res = {"authenticated": doc.get("authenticated"), "session_revoked": doc.get("session_revoked"),
               "store": doc.get("store"), "units": units, "last_incoming": self.when(last_in)}
        if self.gate_cmd:
            g = self.gate(["status"])
            res["gate"] = {k: g.get(k) for k in ("paused", "strict", "window", "allowlist", "blocked")}
            c = g.get("counters") or {}
            res["gate"]["sent_today"] = {"contacts": c.get("ext_day", 0), "owner": c.get(self.cfg.get("owner_counter", "owner_day"), 0),
                                         "new_contacts": c.get("new_day", 0)}
            res["gate"]["new_contacts_paused"] = os.path.exists(os.path.join(self.state, "PAUSA-NOVOS"))
            res["log"] = self.gate(["verify-log"])
        return res

    def contacts(self):
        allow, block = self.jfile("contacts.json", {}), self.jfile("blocklist.json", {})
        con = self.db()
        names = self.names(con)
        rows = []
        for num in sorted(set(allow) | set(block)):
            last = con.execute("SELECT ts, from_me, COALESCE(text, display_text, '') t FROM messages "
                               "WHERE chat_jid=? AND deleted_at IS NULL ORDER BY ts DESC LIMIT 1",
                               (f"{num}@s.whatsapp.net",)).fetchone()
            a = allow.get(num, {})
            rows.append({"num": num, "name": a.get("name") or names.get(num, ""), "role": a.get("role", ""),
                         "lead": a.get("lead", ""), "added": (a.get("added") or "")[:16].replace("T", " "),
                         "allowed": num in allow, "blocked": num in block,
                         "last": self.when(last["ts"]) if last else "", "last_ts": last["ts"] if last else 0,
                         "preview": (last["t"][:80] if last else "")})
        rows.sort(key=lambda r: -r["last_ts"])
        return {"contacts": rows}

    def chat(self, num, limit=60):
        num = re.sub(r"\D", "", num or "")
        con = self.db()
        mine = set(self.jfile("sent_ids.json", []))
        rows = con.execute("SELECT msg_id, ts, from_me, COALESCE(text, display_text, media_caption, '') t, "
                           "media_type, reaction_emoji FROM messages WHERE chat_jid=? AND deleted_at IS NULL "
                           "ORDER BY ts DESC LIMIT ?", (f"{num}@s.whatsapp.net", min(int(limit), 200))).fetchall()
        msgs = []
        for m in reversed(rows):
            if m["from_me"]:
                who = "agent" if (m["msg_id"] in mine or not self.state) else "owner"
            else:
                who = "owner" if num in self.owner else "contact"
            msgs.append({"who": who, "when": self.when(m["ts"]), "text": m["t"],
                         "media": m["media_type"] or None, "reaction": m["reaction_emoji"] or None})
        return {"num": num, "name": self.names(con).get(num, ""), "messages": msgs}

    def requests(self):
        out = []
        d = os.path.join(self.state, "requests") if self.state else None
        if d and os.path.isdir(d):
            for fn in os.listdir(d):
                try:
                    with open(os.path.join(d, fn)) as f:
                        r = json.load(f)
                except (OSError, ValueError):
                    continue
                out.append({k: r.get(k) for k in ("code", "state", "to", "name", "role", "why", "text", "created")})
        out.sort(key=lambda r: r.get("created") or "", reverse=True)
        return {"requests": out[:50]}

    def unknown(self, days=7):
        allow, block = self.jfile("contacts.json", {}), self.jfile("blocklist.json", {})
        con = self.db()
        names = self.names(con)
        since = int(time.time()) - days * 86400
        rows = con.execute("SELECT chat_jid, COUNT(*) n, MAX(ts) last FROM messages WHERE from_me=0 AND ts>? "
                           "AND chat_jid LIKE '%@s.whatsapp.net' GROUP BY chat_jid ORDER BY last DESC LIMIT 50",
                           (since,)).fetchall()
        out = []
        for r in rows:
            num = self.num_of(r["chat_jid"])
            if num and num not in allow and num not in block and num not in self.owner:
                out.append({"num": num, "name": names.get(num, ""), "count": r["n"], "last": self.when(r["last"])})
        return {"unknown": out}

    # ---------- alertas (push) ----------
    def alerts(self):
        out, base = [], "/#/whatsapp_wacli"
        for r in self.requests()["requests"]:
            if r["state"] == "pending":
                who = r.get("name") or r.get("to")
                out.append({"id": f"req-{r['code']}", "title": f"Pedido de envio: {who}", "urgent": True,
                            "body": (r.get("text") or "")[:300], "url": f"{base}/requests", "tag": f"wa-req-{r['code']}",
                            "actions": [{"action": "approve", "title": "Aprovar",
                                         "post": {"path": "whatsapp_wacli/requests/approve", "body": {"code": r["code"]}}},
                                        {"action": "reject", "title": "Descartar",
                                         "post": {"path": "whatsapp_wacli/requests/reject", "body": {"code": r["code"]}}}]})
        now = time.time()
        if now - getattr(self, "_sess_at", 0) > 60:
            self._sess_at, self._sess = now, self.session_problem()
        if self._sess:
            out.append({"id": f"sess-{self._sess}", "title": "WhatsApp com problema", "body": self._sess,
                        "url": base, "tag": "wa-sess", "urgent": True})
        if self.state and os.path.exists(os.path.join(self.state, "PAUSA-NOVOS")):
            out.append({"id": f"reach-{int(os.path.getmtime(os.path.join(self.state, 'PAUSA-NOVOS')))}",
                        "title": "WhatsApp limitou contatos novos", "url": base, "tag": "wa-reach", "urgent": True,
                        "body": "Prospecção pausada sozinha. Não repareie o número; libere com VOLTA quando passar."})
        for u in self.unknown(days=1)["unknown"]:
            out.append({"id": f"unk-{u['num']}-{u['last']}", "title": f"Mensagem de fora da lista: {u['name'] or u['num']}",
                        "body": "O agente não responde. Toque para ver e liberar.", "url": f"{base}/chat/{u['num']}",
                        "tag": f"wa-unk-{u['num']}"})
        return out

    def session_problem(self):
        for u in self.units:
            p = subprocess.run(["systemctl", "is-active", u], capture_output=True, text=True)
            if p.stdout.strip() not in ("active", "activating"):
                return f"serviço {u} parado"
        try:
            p = subprocess.run([self.wacli, "--store", self.store, "--read-only", "--json", "doctor"],
                               capture_output=True, text=True, timeout=20)
            d = json.loads(p.stdout or "{}").get("data") or {}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return ""
        if d.get("session_revoked"):
            return "o celular desvinculou o aparelho; precisa parear de novo"
        if d.get("authenticated") is False:
            return "sessão desconectada"
        return ""

    # ---------- ações ----------
    def gate(self, args):
        env = {"PATH": "/usr/bin:/bin", "WA_CALLER": "hub", "LANG": "C.UTF-8"}
        p = subprocess.run(self.gate_cmd + args, capture_output=True, text=True, env=env, timeout=60)
        try:
            return json.loads(p.stdout or "{}")
        except ValueError:
            return {"ok": False, "error": (p.stderr or p.stdout)[-300:]}

    def handle(self, method, path, q, body):
        if method == "GET":
            if path == "status":
                return 200, self.status()
            if path == "contacts":
                return 200, self.contacts()
            if path == "chat":
                return 200, self.chat(q.get("num", ""), q.get("limit", 60))
            if path == "requests":
                return 200, self.requests()
            if path == "unknown":
                return 200, self.unknown()
            return 404, {"error": "not found"}
        if not self.gate_cmd:
            return 400, {"error": "this app is read-only without a gate"}
        body = body or {}
        actions = {"contacts/add": "add", "contacts/remove": "remove", "contacts/block": "block",
                   "contacts/unblock": "unblock", "requests/approve": "approve", "requests/reject": "reject",
                   "pause": "pause", "resume": "resume"}
        if path not in actions:
            return 404, {"error": "not found"}
        args = ["admin", actions[path]]
        for k in ("num", "name", "role", "lead", "code"):
            v = body.get(k)
            if v:
                args += [f"--{k}", str(v)[:200]]
        r = self.gate(args)
        return (200 if r.get("ok") else 400), r
