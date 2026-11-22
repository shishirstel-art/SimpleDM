"""Download tasks: segmented HTTP (resumable) and BitTorrent (via libtorrent)."""
import json
import os
import re
import threading
import time
import uuid
from urllib.parse import urlparse, unquote

import requests

try:
    import libtorrent as lt
except ImportError:
    lt = None

CHUNK = 64 * 1024
UA = {"User-Agent": "Mozilla/5.0 (SimpleDM/2.0)"}


def new_id():
    return uuid.uuid4().hex[:8]


def safe_name(n):
    return re.sub(r'[\\/:*?"<>|]', "_", n).strip() or "download.bin"


def unique_path(path):
    base, ext = os.path.splitext(path)
    p, i = path, 1
    while os.path.exists(p) or os.path.exists(p + ".part"):
        p = f"{base} ({i}){ext}"
        i += 1
    return p


def probe(url, headers):
    """Return (final_url, total_size or None, supports_ranges, filename)."""
    h = {**UA, **headers, "Range": "bytes=0-0"}
    with requests.get(url, headers=h, stream=True, allow_redirects=True, timeout=20) as r:
        r.raise_for_status()
        total, ranges = None, False
        if r.status_code == 206:
            m = re.search(r"/(\d+)$", r.headers.get("Content-Range", ""))
            if m:
                total, ranges = int(m.group(1)), True
        elif "Content-Length" in r.headers:
            total = int(r.headers["Content-Length"])
        name = None
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?',
                      r.headers.get("Content-Disposition", ""), re.I)
        if m:
            name = unquote(m.group(1))
        if not name:
            name = unquote(os.path.basename(urlparse(r.url).path)) or "download.bin"
        return r.url, total, ranges, safe_name(name)


# --------------------------------------------------------------------------
class HttpTask:
    kind = "http"

    def __init__(self, url, folder, connections=8, headers=None, tid=None):
        self.id = tid or new_id()
        self.url, self.folder, self.connections = url, folder, connections
        self.headers = headers or {}          # not saved to disk (may hold cookies)
        self.name = safe_name(unquote(os.path.basename(urlparse(url).path)) or "download.bin")
        self.path = None
        self.total, self.done, self.speed = None, 0, 0.0
        self.status, self.error = "queued", ""
        self.ranges, self.segs = False, []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._cancel = False
        self._failed = False
        self._thread = None

    part = property(lambda self: self.path + ".part")
    state_file = property(lambda self: self.path + ".state")

    # ---- persistence -------------------------------------------------
    def to_dict(self):
        return {"kind": "http", "id": self.id, "url": self.url, "folder": self.folder,
                "path": self.path, "name": self.name, "total": self.total,
                "ranges": self.ranges, "status": self.status,
                "connections": self.connections}

    @classmethod
    def from_dict(cls, d):
        t = cls(d["url"], d["folder"], d.get("connections", 8), tid=d["id"])
        t.path, t.name, t.total, t.ranges = d.get("path"), d["name"], d.get("total"), d.get("ranges", False)
        if d["status"] == "done":
            t.status, t.done = "done", t.total or 0
        else:
            t.status = "paused"
            if t.path:
                t._load_state()
        return t

    def _sum(self):
        with self._lock:
            return sum(s["done"] for s in self.segs)

    def _load_state(self):
        try:
            with open(self.state_file) as f:
                d = json.load(f)
            if d["total"] == self.total and os.path.exists(self.part):
                self.segs = d["segs"]
                self.done = self._sum()
                return True
        except Exception:
            pass
        return False

    def _save_state(self):
        with self._lock:
            data = {"total": self.total, "segs": [dict(s) for s in self.segs]}
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.state_file)

    def _prepare(self):
        if self.ranges and self.total:
            if self.segs or self._load_state():
                return
            n = max(1, min(self.connections, self.total // (256 * 1024) or 1))
            size = self.total // n
            self.segs = [{"start": i * size,
                          "end": self.total - 1 if i == n - 1 else (i + 1) * size - 1,
                          "done": 0} for i in range(n)]
            with open(self.part, "wb") as f:
                f.truncate(self.total)
        else:
            self.segs = [{"start": 0, "end": -1, "done": 0}]
            open(self.part, "wb").close()

    # ---- control -----------------------------------------------------
    def update(self):
        pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._failed = False
        self.status, self.error = "downloading", ""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        if self.status == "downloading":
            self._stop.set()
        elif self.status == "queued":
            self.status = "paused"

    def cancel(self):
        self._cancel = True
        self._stop.set()
        if not (self._thread and self._thread.is_alive()):
            self._cleanup()

    def join(self, timeout=3):
        if self._thread:
            self._thread.join(timeout)

    def _cleanup(self):
        if self.path and self.status != "done":
            for p in (self.part, self.state_file):
                try:
                    os.remove(p)
                except OSError:
                    pass
        self.status = "cancelled"

    # ---- worker ------------------------------------------------------
    def _worker(self, i):
        seg = self.segs[i]
        for attempt in range(6):
            if self._stop.is_set():
                return
            if not self.ranges:
                seg["done"] = 0
            pos = seg["start"] + seg["done"]
            if self.ranges and pos > seg["end"]:
                return
            h = {**UA, **self.headers}
            if self.ranges:
                h["Range"] = f"bytes={pos}-{seg['end']}"
            try:
                with requests.get(self.url, headers=h, stream=True, timeout=20) as r:
                    if self.ranges and r.status_code != 206:
                        raise IOError(f"HTTP {r.status_code}")
                    r.raise_for_status()
                    with open(self.part, "r+b") as f:
                        if not self.ranges:
                            f.truncate(0)
                        f.seek(pos)
                        for chunk in r.iter_content(CHUNK):
                            if self._stop.is_set():
                                return
                            f.write(chunk)
                            with self._lock:
                                seg["done"] += len(chunk)
                if not self.ranges or seg["done"] >= seg["end"] - seg["start"] + 1:
                    return
            except Exception as e:
                self.error = str(e)[:80]
                time.sleep(min(2 ** attempt, 10))
        self._failed = True
        self._stop.set()

    def _run(self):
        try:
            if self.path is None:
                url, total, ranges, name = probe(self.url, self.headers)
                self.url, self.total, self.ranges = url, total, ranges
                os.makedirs(self.folder, exist_ok=True)
                self.path = unique_path(os.path.join(self.folder, name))
                self.name = os.path.basename(self.path)
            os.makedirs(self.folder, exist_ok=True)
            self._prepare()

            threads = [threading.Thread(target=self._worker, args=(i,), daemon=True)
                       for i in range(len(self.segs))]
            for t in threads:
                t.start()
            last, t0, last_save = self._sum(), time.time(), 0
            while any(t.is_alive() for t in threads):
                time.sleep(0.5)
                now, d = time.time(), self._sum()
                self.speed = (d - last) / max(now - t0, 1e-6)
                last, t0, self.done = d, now, d
                if self.ranges and now - last_save > 2:
                    self._save_state()
                    last_save = now
            for t in threads:
                t.join()
            self.done, self.speed = self._sum(), 0.0

            if self._cancel:
                self._cleanup()
            elif self._failed:
                if self.ranges:
                    self._save_state()
                self.status = "error"
            elif self._stop.is_set():
                if self.ranges:
                    self._save_state()
                self.status = "paused"
            else:
                os.replace(self.part, self.path)
                if os.path.exists(self.state_file):
                    os.remove(self.state_file)
                if self.total is None:
                    self.total = self.done
                self.status = "done"
        except Exception as e:
            self.error, self.status, self.speed = str(e)[:80], "error", 0.0


# --------------------------------------------------------------------------
_ses = None


def _session():
    global _ses
    if _ses is None:
        _ses = lt.session({"listen_interfaces": "0.0.0.0:6881,[::]:6881"})
    return _ses


class TorrentTask:
    """Magnet links and .torrent files. Needs:  pip install libtorrent"""
    kind = "torrent"

    def __init__(self, source, folder, tid=None):
        self.id = tid or new_id()
        self.source, self.folder = source, folder
        self.name = "(torrent)" if source.startswith("magnet:") else os.path.basename(source)
        self.total, self.done, self.speed, self.peers = None, 0, 0.0, 0
        self.status, self.error = "queued", ""
        self._h = None

    def to_dict(self):
        return {"kind": "torrent", "id": self.id, "source": self.source,
                "folder": self.folder, "name": self.name, "status": self.status}

    @classmethod
    def from_dict(cls, d):
        t = cls(d["source"], d["folder"], tid=d["id"])
        t.name = d["name"]
        t.status = "done" if d["status"] == "done" else "paused"
        return t

    def start(self):
        if lt is None:
            self.status, self.error = "error", "libtorrent missing: pip install libtorrent"
            return
        try:
            if self._h is None:
                ses = _session()
                if self.source.startswith("magnet:"):
                    p = lt.parse_magnet_uri(self.source)
                else:
                    p = lt.add_torrent_params()
                    p.ti = lt.torrent_info(self.source)
                p.save_path = self.folder
                self._h = ses.add_torrent(p)
            else:
                self._h.resume()
            self.status, self.error = "downloading", ""
        except Exception as e:
            self.status, self.error = "error", str(e)[:80]

    def pause(self):
        if self._h is not None and self.status == "downloading":
            self._h.pause()
        if self.status in ("downloading", "queued"):
            self.status, self.speed = "paused", 0.0

    def update(self):
        if self._h is None or self.status != "downloading":
            return
        s = self._h.status()
        self.speed, self.peers = s.download_rate, s.num_peers
        if "metadata" in str(s.state):
            self.name = "(fetching metadata...)"
            return
        self.name = s.name or self.name
        self.total, self.done = s.total_wanted or None, s.total_wanted_done
        if s.is_finished or (s.total_wanted and s.total_wanted_done >= s.total_wanted):
            self._h.pause()
            self.status, self.speed = "done", 0.0

    def cancel(self):
        if self._h is not None and lt is not None:
            try:
                flag = lt.options_t.delete_files if self.status != "done" else 0
                _session().remove_torrent(self._h, flag)
            except Exception:
                pass
        self.status = "cancelled"

    def join(self, timeout=3):
        pass
