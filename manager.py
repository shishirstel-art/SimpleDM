"""Queue manager + config. Runs at most `max_active` downloads at a time."""
import json
import os
import re
from urllib.parse import urlparse

import requests

from engine import HttpTask, TorrentTask, UA, safe_name

HOME = os.path.join(os.path.expanduser("~"), ".simpledm")
CFG_FILE = os.path.join(HOME, "config.json")
QUEUE_FILE = os.path.join(HOME, "queue.json")
DEFAULTS = {"folder": os.path.join(os.path.expanduser("~"), "Downloads"),
            "max_active": 3, "connections": 8}


class Manager:
    def __init__(self):
        os.makedirs(HOME, exist_ok=True)
        self.cfg = dict(DEFAULTS)
        try:
            with open(CFG_FILE) as f:
                self.cfg.update(json.load(f))
        except Exception:
            pass
        self.tasks = []
        self._load()

    # ---- persistence -------------------------------------------------
    def save_cfg(self):
        with open(CFG_FILE, "w") as f:
            json.dump(self.cfg, f, indent=2)

    def save(self):
        with open(QUEUE_FILE, "w") as f:
            json.dump([t.to_dict() for t in self.tasks], f)

    def _load(self):
        try:
            with open(QUEUE_FILE) as f:
                for d in json.load(f):
                    cls = TorrentTask if d["kind"] == "torrent" else HttpTask
                    self.tasks.append(cls.from_dict(d))
        except Exception:
            pass

    # ---- API ---------------------------------------------------------
    def get(self, tid):
        return next((t for t in self.tasks if t.id == tid), None)

    def _fetch_torrent(self, url, headers):
        r = requests.get(url, headers={**UA, **(headers or {})}, timeout=30)
        r.raise_for_status()
        d = os.path.join(HOME, "torrents")
        os.makedirs(d, exist_ok=True)
        name = safe_name(os.path.basename(urlparse(url).path)) or "file.torrent"
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(r.content)
        return p

    def add(self, source, headers=None):
        s = source.strip().strip('"')
        folder = self.cfg["folder"]
        if s.lower().startswith("magnet:") or (s.lower().endswith(".torrent") and os.path.isfile(s)):
            t = TorrentTask(s, folder)
        elif re.match(r"https?://", s, re.I):
            if urlparse(s).path.lower().endswith(".torrent"):
                t = TorrentTask(self._fetch_torrent(s, headers), folder)
            else:
                t = HttpTask(s, folder, self.cfg["connections"], headers)
        else:
            raise ValueError(f"Unsupported link: {s[:60]}")
        self.tasks.append(t)
        return t

    def tick(self):
        for t in self.tasks:
            t.update()
        active = sum(1 for t in self.tasks if t.status == "downloading")
        for t in self.tasks:
            if t.status == "queued" and active < self.cfg["max_active"]:
                t.start()
                active += 1

    def pause(self, t):
        t.pause()

    def resume(self, t):
        if t.status in ("paused", "error"):
            t.status = "queued"

    def remove(self, t):
        t.cancel()
        if t in self.tasks:
            self.tasks.remove(t)

    def shutdown(self):
        for t in self.tasks:
            if t.status == "downloading":
                t.pause()
        for t in self.tasks:
            t.join(4)
        self.save()
