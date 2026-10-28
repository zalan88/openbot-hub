"""Bedtime stories app for OpenBot Hub: a library of stories (text + audio) that plays on the phone or on a
speaker through Home Assistant.

Library: `<library_dir>/stories.json` (list of {id, titulo, licao, texto, duracao_s}) and `<id>.mp3` files.
Speakers fetch the audio from `media_base_url` (for example Home Assistant's /local/ folder on the home
network), so a cast device does not need to reach this hub.
"""
import json
import os
import re
import urllib.request


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dir = cfg["library_dir"]
        self.players = cfg.get("players", [])  # [[entity_id, label], ...]
        self.media_base = cfg.get("media_base_url", "").rstrip("/")
        self.ha_url = cfg.get("ha_url", "").rstrip("/")
        self.token = open(cfg["ha_token_file"]).read().strip() if cfg.get("ha_token_file") else ""
        self.info = {"id": "stories", "name": cfg.get("title", "Histórias"), "icon": "book",
                     "description": cfg.get("description", "Histórias para dormir"),
                     "players": self.players}

    def library(self):
        try:
            with open(os.path.join(self.dir, "stories.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def handle(self, method, path, q, body):
        if method == "GET" and path == "list":
            return 200, {"stories": [{k: s.get(k) for k in ("id", "titulo", "licao", "duracao_s")} for s in self.library()]}
        if method == "GET" and path == "story":
            s = next((s for s in self.library() if s["id"] == q.get("id")), None)
            return (200, s) if s else (404, {"error": "not found"})
        if method == "GET" and path == "audio":
            sid = q.get("id", "")
            if not re.fullmatch(r"[a-z0-9-]{1,60}", sid):
                return 404, {"error": "not found"}
            p = os.path.join(self.dir, f"{sid}.mp3")
            if not os.path.isfile(p):
                return 404, {"error": "not found"}
            with open(p, "rb") as f:
                return 200, (f.read(), "audio/mpeg")
        if method == "POST" and path == "play":
            sid, player = (body or {}).get("id", ""), (body or {}).get("player", "")
            if player not in [p[0] for p in self.players] or not any(s["id"] == sid for s in self.library()):
                return 400, {"error": "história ou caixa de som inválida"}
            data = json.dumps({"entity_id": player, "media_content_id": f"{self.media_base}/{sid}.mp3",
                               "media_content_type": "music"}).encode()
            req = urllib.request.Request(f"{self.ha_url}/api/services/media_player/play_media", data=data, method="POST",
                                         headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=15):
                    return 200, {"ok": True}
            except OSError as e:
                return 502, {"error": str(e)[:200]}
        return 404, {"error": "not found"}
