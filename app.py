#!/usr/bin/env python3
"""SimpleDM - download manager GUI (Tkinter). Run:  python app.py"""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import server
from manager import Manager


def fmt_size(n):
    if not n:
        return "?"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_eta(t):
    if t.status != "downloading" or not t.total or t.speed < 1:
        return ""
    s = int((t.total - t.done) / t.speed)
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m {s % 60}s"


class App:
    def __init__(self, root, mgr, inbox):
        self.root, self.mgr, self.inbox, self.n = root, mgr, inbox, 0
        root.title("SimpleDM")
        root.geometry("920x420")

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in [("Add", self.add), ("Add .torrent", self.add_torrent_file),
                          ("Pause", self.pause), ("Resume", self.resume),
                          ("Remove", self.remove), ("Open folder", self.open_folder),
                          ("Settings", self.settings)]:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)

        cols = [("name", "Name", 340), ("size", "Size", 90), ("progress", "Progress", 80),
                ("speed", "Speed", 90), ("eta", "ETA", 80), ("status", "Status", 120)]
        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings",
                                 selectmode="extended")
        for key, title, w in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, anchor="w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    # ---- loop --------------------------------------------------------
    def tick(self):
        while not self.inbox.empty():
            d = self.inbox.get()
            h = {}
            if d.get("referrer"):
                h["Referer"] = d["referrer"]
            if d.get("cookie"):
                h["Cookie"] = d["cookie"]
            try:
                self.mgr.add(d["url"], headers=h)
            except Exception as e:
                print("Extension add failed:", e)
        self.mgr.tick()
        self.refresh()
        self.n += 1
        if self.n % 10 == 0:
            self.mgr.save()
        self.root.after(500, self.tick)

    def refresh(self):
        ids = {t.id for t in self.mgr.tasks}
        for iid in self.tree.get_children():
            if iid not in ids:
                self.tree.delete(iid)
        for t in self.mgr.tasks:
            pct = f"{t.done * 100 / t.total:.1f}%" if t.total else "-"
            status = t.status + (f" ({t.error})" if t.status == "error" and t.error else "")
            if t.kind == "torrent" and t.status == "downloading":
                status += f" · {t.peers} peers"
            vals = (t.name, fmt_size(t.total), pct,
                    f"{fmt_size(t.speed)}/s" if t.status == "downloading" else "",
                    fmt_eta(t), status)
            if self.tree.exists(t.id):
                self.tree.item(t.id, values=vals)
            else:
                self.tree.insert("", "end", iid=t.id, values=vals)

    def selected(self):
        return [t for t in (self.mgr.get(i) for i in self.tree.selection()) if t]

    # ---- actions -----------------------------------------------------
    def add(self):
        win = tk.Toplevel(self.root)
        win.title("Add downloads")
        ttk.Label(win, text="One link per line (http/https, magnet:, or .torrent URL):").pack(
            anchor="w", padx=8, pady=(8, 2))
        box = tk.Text(win, width=70, height=8)
        box.pack(padx=8)
        try:
            clip = self.root.clipboard_get()
            if clip.strip().lower().startswith(("http", "magnet:")):
                box.insert("1.0", clip.strip())
        except tk.TclError:
            pass

        def go():
            errs = []
            for line in box.get("1.0", "end").splitlines():
                if line.strip():
                    try:
                        self.mgr.add(line)
                    except Exception as e:
                        errs.append(str(e))
            win.destroy()
            if errs:
                messagebox.showerror("Some links failed", "\n".join(errs[:5]))
        ttk.Button(win, text="Download", command=go).pack(pady=8)

    def add_torrent_file(self):
        for p in filedialog.askopenfilenames(filetypes=[("Torrent", "*.torrent")]):
            try:
                self.mgr.add(p)
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def pause(self):
        for t in self.selected():
            self.mgr.pause(t)

    def resume(self):
        for t in self.selected():
            self.mgr.resume(t)

    def remove(self):
        sel = self.selected()
        if sel and messagebox.askyesno("Remove", f"Remove {len(sel)} item(s)?\n"
                                       "Unfinished partial files are deleted."):
            for t in sel:
                self.mgr.remove(t)

    def open_folder(self):
        sel = self.selected()
        path = self.mgr.cfg["folder"]
        if sel:
            p = getattr(sel[0], "path", None)
            path = os.path.dirname(p) if p else sel[0].folder
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def settings(self):
        win = tk.Toplevel(self.root)
        win.title("Settings")
        cfg = self.mgr.cfg
        vf, va, vc = tk.StringVar(value=cfg["folder"]), tk.IntVar(value=cfg["max_active"]), \
            tk.IntVar(value=cfg["connections"])
        ttk.Label(win, text="Download folder").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(win, textvariable=vf, width=40).grid(row=0, column=1, padx=4)
        ttk.Button(win, text="...", width=3, command=lambda: vf.set(
            filedialog.askdirectory() or vf.get())).grid(row=0, column=2, padx=4)
        ttk.Label(win, text="Max simultaneous downloads").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(win, from_=1, to=10, textvariable=va, width=5).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(win, text="Connections per file").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(win, from_=1, to=32, textvariable=vc, width=5).grid(row=2, column=1, sticky="w", padx=4)

        def ok():
            cfg.update(folder=vf.get(), max_active=va.get(), connections=vc.get())
            self.mgr.save_cfg()
            win.destroy()
        ttk.Button(win, text="Save", command=ok).grid(row=3, column=1, pady=8)

    def close(self):
        self.mgr.shutdown()
        self.root.destroy()


def main():
    mgr = Manager()
    try:
        inbox = server.start()
    except OSError:
        print("Port 9614 busy (is SimpleDM already running?). Browser extension disabled.")
        import queue
        inbox = queue.Queue()
    root = tk.Tk()
    App(root, mgr, inbox)
    root.mainloop()


if __name__ == "__main__":
    main()
