"""
lan_chat_tk.py - tkinter front end for peer.py (Modules 1-3), "creature mesh" theme.

Put this file in the same folder as peer.py and peers.json, then run:
    python lan_chat_tk.py --id A --port 5001 --config peers.json

It replaces the console UI of peer.py. peer.py itself is NOT modified:
this file imports it, runs the same Node (sockets, heartbeats, distance
vector routing, ACKs, retries) and only changes how events are shown[cite: 1].

Only BMP characters are used for symbols (no colour emoji) so it works on
every Tk build. Mascots are drawn on Canvas, so no image files are needed.
"""
import queue
import re
import threading
import time
import tkinter as tk

import peer

C = dict(bg="#fff8ec", ink="#2a2840", mute="#8a8799", white="#ffffff",
         pink="#ffe1e5", pinkd="#d93a4f", coral="#f4646f", coral_d="#e2475a",
         mint="#d9f6e8", mintd="#16805a", yellow="#ffd75e", yellow_l="#fff1b8",
         lav="#ece7ff", lavd="#5b47c9", sky="#d8ecff", skyd="#2c5f9e",
         sel="#fff0f2", code="#f6f1e3", up="#2fbf80", off="#f0566a")
PALETTE = ["#ffd9a8", "#c9f0dc", "#d9ccff", "#ffc9d6", "#bfe3ff", "#fff0a8"]

HEAD = ("Trebuchet MS", 11, "bold")
BIG = ("Trebuchet MS", 17, "bold")
SANS = ("Segoe UI", 10)
MONO = ("Consolas", 9)
MONO_B = ("Consolas", 9, "bold")
BTN = ("Trebuchet MS", 9, "bold")

# Canvas drawing scale factor (derived from display DPI)
SCALE = 1.0


def px(n):
    return int(n * SCALE)


def fmt(ts):
    return time.strftime("%H:%M", time.localtime(ts))


def hexcrc(v):
    try:
        return format(int(v), "08x")
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------------------
# SMALL DRAWING / WIDGET HELPERS
# ---------------------------------------------------------------------------

def card(parent, bg, pbg, shadow=4, border=2):
    """A box with a dark outline and a hard offset shadow (sticker look).
    Returns (wrapper, inner). Pack/grid the wrapper, put content in inner."""
    sh, bd = shadow, max(1, border)
    w = tk.Frame(parent, bg=pbg)
    w.columnconfigure(0, weight=1)
    w.rowconfigure(0, weight=1)
    tk.Frame(w, bg=C["ink"]).grid(row=0, column=0, sticky="nsew", padx=(sh, 0), pady=(sh, 0))
    inner = tk.Frame(w, bg=bg, highlightbackground=C["ink"], highlightcolor=C["ink"], highlightthickness=bd)
    inner.grid(row=0, column=0, sticky="nsew", padx=(0, sh), pady=(0, sh))
    return w, inner


def chunky(parent, pbg, text, bg, fg, cmd, padx=12, pady=4, shadow=3):
    """Outlined button with a hard shadow. Returns (wrapper, button)."""
    w, inner = card(parent, bg, pbg, shadow)
    b = tk.Button(inner, text=text, bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                  disabledforeground=C["mute"], relief="flat", bd=0, font=BTN, padx=padx,
                  pady=pady, cursor="hand2", command=cmd)
    b.pack(fill="both", expand=True)
    return w, b


def pill(parent, text, fg, bg, border=None, font=MONO_B, padx=8, pady=1):
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=font, padx=padx, pady=pady,
                    highlightbackground=border or fg, highlightcolor=border or fg, highlightthickness=1)


def rrect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def creature(parent, pid, size, awake, bg, dot=True, me=False):
    """Draw a little mascot. Awake = open eyes + smile, asleep = closed eyes, night cap, z's."""
    s = px(size)
    lw = max(2, px(2))
    ink = C["ink"]
    c = tk.Canvas(parent, width=s, height=s, bg=bg, highlightthickness=0)
    fill = PALETTE[sum(ord(ch) for ch in str(pid)) % len(PALETTE)]
    if me:                                              # antenna
        c.create_line(s * .5, s * .22, s * .5, s * .08, fill=ink, width=lw)
        c.create_oval(s * .44, s * .02, s * .56, s * .14, fill=C["coral"], outline=ink, width=lw)
    else:                                               # ears
        for ex in (.22, .78):
            c.create_oval(s * (ex - .1), s * .14, s * (ex + .1), s * .34, fill=fill, outline=ink, width=lw)
    rrect(c, s * .1, s * .2, s * .9, s * .9, s * .22, fill=fill, outline=ink, width=lw)
    ey, r = s * .52, s * .06
    for ex in (.34, .66):
        if awake:
            c.create_oval(s * ex - r, ey - r, s * ex + r, ey + r, fill=ink, outline=ink)
        else:
            c.create_arc(s * ex - r * 1.3, ey - r * 1.3, s * ex + r * 1.3, ey + r * 1.3,
                         start=200, extent=140, style="arc", outline=ink, width=lw)
    for ex in (.22, .78):                               # cheeks
        c.create_oval(s * ex - s * .06, s * .63, s * ex + s * .06, s * .7, fill="#ff9fb0", outline="")
    if awake:
        c.create_arc(s * .4, s * .56, s * .6, s * .74, start=200, extent=140, style="arc", outline=ink, width=lw)
    else:
        c.create_oval(s * .47, s * .66, s * .53, s * .72, outline=ink, width=max(1, lw - 1))
        c.create_polygon(s * .2, s * .3, s * .8, s * .3, s * .62, s * .04, fill=C["lav"], outline=ink, width=lw)
        c.create_oval(s * .55, s * -.02 + s * .02, s * .69, s * .12, fill=C["white"], outline=ink, width=lw)
        c.create_text(s * .86, s * .1, text="z", font=("Trebuchet MS", -max(8, int(s * .2)), "bold"), fill=C["lavd"])
        if size >= 100:                                 # blanket for the big hero version
            rrect(c, s * .14, s * .68, s * .86, s * .94, s * .08, fill=C["yellow"], outline=ink, width=lw)
    if dot:
        d = s * .3
        c.create_oval(s - d - 1, s - d - 1, s - 1, s - 1, fill=C["up"] if awake else C["off"],
                      outline=bg, width=max(2, px(2)))
    return c


def bind_click(w, cb):
    w.bind("<Button-1>", cb)
    for ch in w.winfo_children():
        bind_click(ch, cb)


# ---------------------------------------------------------------------------
# NODE WITH A GUI-FRIENDLY EVENT LOG
# ---------------------------------------------------------------------------

class GuiNode(peer.Node):
    """peer.Node plus a message log the window can read[cite: 1]."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.log = []                               # incoming, outgoing and link events[cite: 1]
        self.log_lock = threading.Lock()
        self.counter = 0
        self.sent_at = {}                           # msg id -> time first sent (for ACK round trip)[cite: 1]
        self.last_rtt = None                        # ms, last clean (no retry) ACK round trip[cite: 1]
        self.last_rtt_ts = 0
        self.forwarded = 0                          # chats/acks I relayed for other peers[cite: 1]
        self.dropped = 0                            # relays dropped: TTL expired, no route, forward failed[cite: 1]
        self.crc_blocked = 0 
        self.plain = {}                       # messages dropped by the CRC check[cite: 1]

    def add(self, rec):
        with self.log_lock:
            self.counter += 1
            rec["n"] = self.counter
            self.log.append(rec)
        return rec

    def say(self, text):
        for line in text.split("\n"):
            m = re.match(r"\[LINK (UP|DOWN)\] (?:no heartbeat from )?(\S+)", line)
            if m:
                if m.group(2) in self.neighbours:
                    self.add({"dir": "sys", "kind": m.group(1).lower(), "peer": m.group(2),
                              "payload": line, "ts": time.time()})
            elif line.startswith("[FORWARD] "):
                self.forwarded += 1
            elif line.startswith(("[TTL EXPIRED]", "[NO ROUTE]", "[FORWARD FAILED]")):
                self.dropped += 1

    def handle_ack(self, msg):
        """Same as Node.handle_ack, plus a round-trip time for the Mesh Pulse card[cite: 1]."""
        mid = msg["payload"]
        fresh = False
        if msg["dst"] == self.id:
            with self.lock:
                e = self.pending.get(mid)
                fresh = e is not None and e["status"] != "DELIVERED" and e["retries"] == 0
        super().handle_ack(msg)
        if fresh and mid in self.sent_at:
            self.last_rtt = (time.time() - self.sent_at[mid]) * 1000
            self.last_rtt_ts = time.time()

        def deliver(self, msg):
            with self.lock:
                duplicate = msg["id"] in self.seen
            if not duplicate:
                text = peer.decrypt_text(msg["payload"])
                if text is not None:
                    self.add({"dir": "in", "peer": msg["src"], "payload": text,
                            "ts": time.time(), "crc_ok": True, "fields": dict(msg)})
            super().deliver(msg)

    def send_gui(self, dst, text, corrupt=False):
        """Same as Node.send_chat, plus the demo option to break the CRC[cite: 1]."""
        hop = self.next_hop(dst)
        if hop is None:
            return f"No route to {dst}"
        msg = peer.build_message(self.id, dst, peer.encrypt_text(text))
        if corrupt:
            msg["crc"] ^= 1
        entry = {"msg": msg, "dst": dst, "text": text, "status": "SENT",
                 "retries": 0, "deadline": time.time() + peer.ACK_TIMEOUT}
        with self.lock:
            self.pending[msg["id"]] = entry
            self.outbox.append(msg["id"])
        self.sent_at[msg["id"]] = time.time()
        self.plain[msg["id"]] = text
        rec = self.add({"dir": "out", "peer": dst, "mid": msg["id"], "ts": time.time(),
                        "corrupted": corrupt, "note": ""})
        ok, reason = peer.send_to_peer(self.neighbours[hop], peer.serialize(msg))
        if not ok:
            rec["note"] = f"Could not reach {hop}: {reason}. Will retry."
        return None


def gui_handle_connection(conn, node):
    """peer.handle_connection, but a CRC failure at the destination is logged for the UI[cite: 1]."""
    with conn:
        try:
            reader = conn.makefile("r", encoding="utf-8")
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                msg = peer.parse(line)
                if msg is None:
                    continue
                if not peer.verify_crc(msg):
                    node.crc_blocked += 1
                    if msg["type"] == "chat" and msg["dst"] == node.id:
                        node.add({"dir": "in", "peer": msg["src"], "payload": str(msg["payload"]),
                                  "ts": time.time(), "dropped": True, "crc_ok": False,
                                  "fields": dict(msg)})
                    continue
                node.handle_message(msg)
        except (OSError, UnicodeDecodeError):
            return


# ---------------------------------------------------------------------------
# WINDOW
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root, node):
        self.root = root
        self.node = node
        root.title(f"Peer {node.id} \u00b7 ECHO LAN Chat")
        root.geometry("1200x740")
        root.minsize(900, 560)
        root.configure(bg=C["bg"])

        self.state = None
        self.selected = None
        self.tab = "all"
        self.corrupt = False
        self.open_msgs = set()
        self.seen_in = {}
        self.known_extra = set()   # peers learned through routing (not in peers.json)
        self.list_sig = None
        self.thread_sig = None
        self.top_sig = None
        self.me_sig = None
        self.hero = None
        self.age_lbl = None
        self.hint_shown = False
        self.toasts = queue.Queue()

        self.build_ui()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    def close(self):
        self.node.running = False
        self.root.destroy()

    # ---------- UI skeleton ----------
    def build_ui(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        self.build_topbar()
        body = tk.Frame(root, bg=C["bg"])
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)
        self.build_sidebar(body)
        tk.Frame(body, bg=C["ink"], width=2).grid(row=0, column=1, sticky="ns")
        self.build_main(body)
        self.toast_lbl = tk.Label(root, bg=C["ink"], fg="white", font=MONO_B, padx=14, pady=6)

    def stat_card(self, parent, bg):
        w, inner = card(parent, bg, C["white"], shadow=2, border=2)
        lbl = tk.Label(inner, bg=bg, fg=C["ink"], font=MONO_B, padx=10, pady=4)
        lbl.pack()
        w.pack(side="left", padx=6, pady=8)
        return lbl

    def build_topbar(self):
        bar = tk.Frame(self.root, bg=C["white"])
        bar.grid(row=0, column=0, sticky="ew")
        tk.Frame(self.root, bg=C["ink"], height=2).grid(row=0, column=0, sticky="sew")
        creature(bar, self.node.id, 40, True, C["white"], dot=False, me=True).pack(side="left", padx=(14, 6), pady=8)
        tk.Label(bar, text="ECHO", font=("Trebuchet MS", 17, "bold"), bg=C["white"], fg=C["ink"]).pack(side="left")
        tk.Label(bar, text="lan pals", font=SANS, bg=C["white"], fg=C["mute"]).pack(side="left", padx=(6, 8))
        pill(bar, "creature-mesh", C["ink"], C["code"]).pack(side="left", padx=(0, 10))
        self.pulse_lbl = self.stat_card(bar, C["pink"])
        self.rest_lbl = self.stat_card(bar, C["lav"])
        self.bcast_lbl = self.stat_card(bar, C["yellow_l"])
        self.reach_lbl = self.stat_card(bar, C["mint"])
        self.reach_card = self.reach_lbl

    def build_sidebar(self, body):
        side = tk.Frame(body, bg=C["bg"], width=320)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.rowconfigure(2, weight=1)
        side.columnconfigure(0, weight=1)

        head = tk.Frame(side, bg=C["bg"])
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        tk.Label(head, text="MESH COMPANIONS", font=("Trebuchet MS", 10, "bold"), bg=C["bg"],
                 fg=C["skyd"]).pack(side="left")
        self.count = pill(head, "0 BOTS", C["ink"], C["yellow"])
        self.count.pack(side="left", padx=8)
        w, _ = chunky(head, C["bg"], "+ Sniff LAN", C["white"], C["ink"], self.sniff, padx=8, pady=3, shadow=2)
        w.pack(side="right")

        tw, ti = card(side, C["white"], C["bg"], shadow=3)
        tw.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        self.tab_btns = {}
        for key, label in (("all", "All"), ("direct", "Direct"), ("multi", "Multi-hop")):
            b = tk.Button(ti, text=label, relief="flat", bd=0, padx=10, pady=5, font=BTN,
                          cursor="hand2", command=lambda k=key: self.set_tab(k))
            b.pack(side="left", fill="x", expand=True, padx=2, pady=2)
            self.tab_btns[key] = b
        self.style_tabs()

        self.list_frame = tk.Frame(side, bg=C["bg"])
        self.list_frame.grid(row=2, column=0, sticky="nsew")

        mw, self.me_frame = card(side, C["mint"], C["bg"], shadow=4)
        mw.grid(row=3, column=0, sticky="ew", padx=14, pady=14)

    def build_main(self, body):
        main = tk.Frame(body, bg=C["bg"])
        main.grid(row=0, column=2, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        self.top = tk.Frame(main, bg=C["white"], height=76)
        self.top.grid(row=0, column=0, sticky="ew")
        tk.Frame(main, bg=C["ink"], height=2).grid(row=0, column=0, sticky="sew")

        wrap = tk.Frame(main, bg=C["bg"])
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.thread = tk.Text(wrap, bg=C["bg"], bd=0, highlightthickness=0, wrap="word", state="disabled",
                              cursor="arrow", padx=20, pady=12, font=("Segoe UI", 11))
        sb = tk.Scrollbar(wrap, command=self.thread.yview)
        self.thread.configure(yscrollcommand=sb.set)
        self.thread.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.config_tags()

        # status strip
        sw, si = card(main, C["white"], C["bg"], shadow=3)
        sw.grid(row=2, column=0, pady=(4, 8))
        self.strip = tk.Label(si, font=MONO, bg=C["white"], fg=C["mute"], padx=16, pady=4)
        self.strip.pack()

        # composer
        comp = tk.Frame(main, bg=C["bg"])
        comp.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 6))
        comp.columnconfigure(0, weight=1)
        ew, ei = card(comp, C["white"], C["bg"], shadow=3)
        ew.grid(row=0, column=0, sticky="ew", padx=(0, 14))
        self.entry = tk.Entry(ei, font=("Segoe UI", 11), relief="flat", bd=0, bg=C["white"],
                            disabledbackground=C["white"], highlightthickness=0)
        self.entry.pack(fill="x", padx=12, pady=8, ipady=4)
        self.entry.bind("<Return>", lambda e: self.send())
        self.entry.bind("<Key>", lambda e: self.root.after_idle(self.update_ph))
        self.ph = tk.Label(self.entry, bg=C["white"], fg=C["mute"], font=("Segoe UI", 11), cursor="xterm")
        self.ph.bind("<Button-1>", lambda e: self.entry.focus_set())
        sw2, self.send_btn = chunky(comp, C["bg"], "Send \u27a4", C["coral"], "white", self.send, padx=22, pady=7)
        self.send_btn.configure(font=("Trebuchet MS", 11, "bold"))
        sw2.grid(row=0, column=1)

        # bot lab
        lab = tk.Frame(main, bg=C["bg"])
        lab.grid(row=4, column=0, sticky="ew", padx=24, pady=(6, 14))
        r1 = tk.Frame(lab, bg=C["bg"])
        r1.pack(fill="x")
        tk.Label(r1, text="Bot Lab:", font=MONO, bg=C["bg"], fg=C["mute"]).pack(side="left", padx=(0, 10))
        tw2, self.tamper = chunky(r1, C["bg"], "Corrupt CRC (demo)", C["yellow"], C["ink"], self.toggle_corrupt)
        tw2.pack(side="left", padx=(0, 10))
        self.hint = pill(r1, "", C["pinkd"], C["pink"], font=MONO_B, padx=10, pady=4)
        r2 = tk.Frame(lab, bg=C["bg"])
        r2.pack(fill="x", pady=(8, 0))
        fw, _ = chunky(r2, C["bg"], "Force Ping", C["white"], C["ink"], self.force_ping)
        fw.pack(side="left", padx=(0, 10))
        pill(r2, "CRC-32 Sentinel: GUARDING", C["mintd"], C["mint"], padx=10, pady=4).pack(side="left")

    def config_tags(self):
        t = self.thread
        t.tag_configure("date", justify="center", foreground=C["ink"], background=C["white"], font=MONO_B,
                        spacing1=6, spacing3=12)
        t.tag_configure("banner", justify="center", foreground=C["mute"], font=MONO, spacing3=10)
        t.tag_configure("center", justify="center", spacing1=10, spacing3=10)
        t.tag_configure("sys", justify="center", foreground=C["pinkd"], background=C["pink"], font=MONO,
                        spacing1=4, spacing3=10)
        t.tag_configure("sys_up", justify="center", foreground=C["mintd"], background=C["mint"], font=MONO,
                        spacing1=4, spacing3=10)
        t.tag_configure("in_meta", foreground=C["mute"], font=MONO, lmargin1=4, lmargin2=4, spacing1=10)
        t.tag_configure("out_meta", foreground=C["mute"], font=MONO, justify="right",
                        lmargin1=220, lmargin2=220, rmargin=4, spacing1=10)
        t.tag_configure("in_bubble", background=C["white"], lmargin1=12, lmargin2=12, rmargin=220,
                        spacing1=5, spacing3=5)
        t.tag_configure("out_bubble", background=C["yellow_l"], justify="right", lmargin1=220,
                        lmargin2=220, rmargin=12, spacing1=5, spacing3=5)
        t.tag_configure("bad_bubble", background=C["pink"], foreground=C["ink"])
        t.tag_configure("note", foreground=C["pinkd"], font=("Consolas", 9, "bold"))
        t.tag_configure("chip_ok", foreground=C["mintd"], font=MONO_B)
        t.tag_configure("chip_bad", foreground=C["pinkd"], font=MONO_B)
        t.tag_configure("chip", foreground=C["mute"], font=MONO)
        t.tag_configure("in_chips", lmargin1=4, lmargin2=4)
        t.tag_configure("out_chips", justify="right", lmargin1=220, lmargin2=220, rmargin=4)
        t.tag_configure("detail", font=MONO, background=C["code"], foreground=C["ink"])
        t.tag_configure("in_detail", lmargin1=12, lmargin2=12, rmargin=220)
        t.tag_configure("out_detail", lmargin1=220, lmargin2=220, rmargin=12)

    # ---------- state: built straight from the Node ----------
    def build_state(self):
        node = self.node
        inf = peer.INFINITY
        with node.lock:
            routes = {d: dict(r) for d, r in node.routes.items()}
            neigh = {k: dict(v) for k, v in node.neighbours.items()}
            pend = {k: (v["status"], v["retries"], dict(v["msg"])) for k, v in node.pending.items()}

        def route_info(pid):
            r = routes.get(pid)
            if r and r["cost"] < inf and r["next"] != node.id:
                return r["next"], r["cost"]
            return None, None

        peers = []
        for nid, n in neigh.items():
            via, cost = route_info(nid)
            peers.append(dict(id=nid, direct=True, reachable=via is not None, via=via, cost=cost,
                              ip=n["ip"], port=n["port"], status=n["status"],
                              age=time.time() - n["last_seen"]))
        self.known_extra.update(d for d in routes if d != node.id and d not in neigh)
        for d in sorted(self.known_extra):
            via, cost = route_info(d)
            peers.append(dict(id=d, direct=False, reachable=via is not None, via=via, cost=cost,
                              ip="", port="", status=""))

        with node.log_lock:
            log = list(node.log)
        msgs = []
        names = {"DELIVERED": "delivered", "SENT": "sent", "FAILED": "failed"}
        for rec in log:
            if rec["dir"] != "out":
                msgs.append(rec)
                continue
            st, retries, msg = pend[rec["mid"]]
            status = names[st]
            msgs.append(dict(n=rec["n"], dir="out", peer=rec["peer"], payload=node.plain.get(rec["mid"], msg["payload"]), ts=rec["ts"],
                           status=status, retries=retries, corrupted=rec["corrupted"],
                           reason=f"no ack after {peer.MAX_RETRIES} retries" if status == "failed" else "",
                           note=rec["note"] if status == "sent" else "", fields=msg))
        return dict(me=node.id, port=node.port, peers=peers, messages=msgs)

    # ---------- helpers ----------
    def tick(self):
        self.state = self.build_state()
        self.render()
        try:
            while True:
                self.toast(self.toasts.get_nowait())
        except queue.Empty:
            pass
        if self.node.running:
            self.root.after(300, self.tick)

    def toast(self, msg):
        self.toast_lbl.configure(text=msg)
        self.toast_lbl.place(relx=0.5, rely=0.88, anchor="center")
        self.root.after(3000, self.toast_lbl.place_forget)

    def msgs_for(self, pid):
        return [m for m in self.state["messages"] if m["peer"] == pid and m["dir"] != "sys"]

    def peer_by_id(self, pid):
        return next((p for p in self.state["peers"] if p["id"] == pid), None)

    @staticmethod
    def link_label(p, short=False):
        if not p["reachable"]:
            return "Unreachable"
        if p["via"] == p["id"]:
            return "Direct" if short else "Direct link"
        return f"via {p['via']}"

    def set_tab(self, k):
        self.tab = k
        self.style_tabs()
        self.list_sig = None
        if self.state:
            self.render_list()

    def style_tabs(self):
        for k, b in self.tab_btns.items():
            on = k == self.tab
            bg, fg = (C["ink"], "white") if on else (C["white"], C["ink"])
            b.configure(bg=bg, fg=fg, activebackground=bg, activeforeground=fg)

    def toggle_corrupt(self):
        self.corrupt = not self.corrupt
        self.render_composer()

    def sniff(self):
        """Ask the node to send its routing table (distance vector) to every live neighbour now."""
        self.node.trigger.set()
        self.toast("Routing update sent to your neighbours")

    def force_ping(self):
        """Send a heartbeat to every neighbour right now instead of waiting for the 2 s timer."""
        n = self.node
        for nid, nb in list(n.neighbours.items()):
            hb = peer.build_message(n.id, nid, "", "heartbeat", ttl=1)
            n.send_async(nb, peer.serialize(hb), peer.HEARTBEAT_TIMEOUT)
        self.toast(f"Heartbeat sent to {len(n.neighbours)} neighbours")

    def traceroute(self):
        p = self.peer_by_id(self.selected) if self.selected else None
        me = self.state["me"]
        if not p:
            self.toast("Pick a peer first")
        elif not p["reachable"]:
            self.toast(f"No route to Peer {p['id']}")
        elif p["via"] == p["id"]:
            self.toast(f"{me} \u2192 {p['id']}  (direct, cost {p['cost']})")
        else:
            self.toast(f"{me} \u2192 {p['via']} \u2192 \u2026 \u2192 {p['id']}  (cost {p['cost']})")

    def select(self, pid):
        self.selected = pid
        self.thread_sig = self.list_sig = self.top_sig = None
        self.render()
        self.entry.focus_set()

    def send(self):
        text = self.entry.get().strip()
        if not text or not self.selected or str(self.entry["state"]) == "disabled":
            return
        dst = self.selected
        if self.node.next_hop(dst) is None:
            self.toast(f"No route to {dst}")
            return
        corrupt = self.corrupt
        self.entry.delete(0, "end")
        self.update_ph()
        self.corrupt = False
        self.render_composer()

        def work():
            err = self.node.send_gui(dst, text, corrupt)
            if err:
                self.toasts.put(err)

        threading.Thread(target=work, daemon=True).start()

    def update_ph(self):
        if self.entry.get():
            self.ph.place_forget()
        else:
            self.ph.place(x=2, rely=0.5, anchor="w")

    # ---------- render ----------
    def render(self):
        s = self.state
        if not self.selected or not self.peer_by_id(self.selected):
            first = next((p for p in s["peers"] if p["direct"]), None) or (s["peers"][0] if s["peers"] else None)
            self.selected = first["id"] if first else None
        if self.selected:
            self.seen_in[self.selected] = sum(1 for m in self.msgs_for(self.selected) if m["dir"] == "in")
        self.render_topbar()
        self.render_list()
        self.render_me()
        self.render_top()
        self.render_thread()
        self.render_composer()

    def render_topbar(self):
        s = self.state
        total = len(s["peers"])
        reach = sum(1 for p in s["peers"] if p["reachable"])
        down = total - reach
        rtt = self.node.last_rtt
        if rtt is not None and time.time() - self.node.last_rtt_ts < 30:
            self.pulse_lbl.configure(text=f"\u2665 Mesh Pulse: {rtt:.0f} ms (ACK round trip)")
        else:
            self.pulse_lbl.configure(text="\u2665 Mesh Pulse: -- ms (quiet)")
        self.rest_lbl.configure(text=f"Awake Bots: {down} of {total} resting")
        self.bcast_lbl.configure(text=f"Broadcast: :{s['port']}")
        self.reach_lbl.configure(text=f"{reach} reachable   {down} snoozing")

    def render_list(self):
        s = self.state
        shown = [p for p in s["peers"]
                 if self.tab == "all" or (self.tab == "direct" and p["direct"]) or (self.tab == "multi" and not p["direct"])]
        rows = []
        for p in shown:
            ms = self.msgs_for(p["id"])
            last = ms[-1] if ms else None
            inc = sum(1 for m in ms if m["dir"] == "in")
            unread = p["id"] != self.selected and inc > self.seen_in.get(p["id"], 0)
            rows.append((p, last, unread))
        sig = (self.tab, self.selected, tuple(
            (p["id"], p["reachable"], p["via"], last["n"] if last else None, last.get("status") if last else None, unread)
            for p, last, unread in rows))
        self.count.configure(text=f"{len(s['peers'])} BOTS")
        if sig == self.list_sig:
            return
        self.list_sig = sig
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not rows:
            tk.Label(self.list_frame, text="No multi-hop peers learned yet." if self.tab == "multi" else "No peers.",
                     bg=C["bg"], fg=C["mute"], font=MONO, pady=20).pack()
        for p, last, unread in rows:
            self.peer_item(p, last, unread)

    def peer_item(self, p, last, unread):
        sel = p["id"] == self.selected
        bg = C["sel"] if sel else C["white"]
        w, inner = card(self.list_frame, bg, C["bg"], shadow=4)
        w.pack(fill="x", padx=14, pady=7)
        if sel:
            tk.Frame(inner, bg=C["coral"], width=7).pack(side="left", fill="y")
        av = creature(inner, p["id"], 46, p["reachable"], bg)
        av.pack(side="left", padx=10, pady=10)
        body = tk.Frame(inner, bg=bg)
        body.pack(side="left", fill="x", expand=True, pady=8, padx=(0, 10))

        r1 = tk.Frame(body, bg=bg)
        r1.pack(fill="x")
        tk.Label(r1, text=f"Peer {p['id']}" + ("" if p["reachable"] else " \u263e"), font=HEAD, bg=bg,
                 fg=C["ink"]).pack(side="left")
        if not p["reachable"]:
            badge = pill(r1, "UNREACHABLE", C["pinkd"], C["pink"], font=("Consolas", 8, "bold"))
        elif p["via"] == p["id"]:
            badge = pill(r1, "ACTIVE", C["mintd"], C["mint"], font=("Consolas", 8, "bold"))
        else:
            badge = pill(r1, f"VIA {p['via']}", C["lavd"], C["lav"], font=("Consolas", 8, "bold"))
        badge.pack(side="right")

        if not p["reachable"]:
            st, col = ("\u25cf Asleep \u00b7 " + ("link down" if p["direct"] else "no route")), C["pinkd"]
        elif p["via"] == p["id"]:
            st, col = "\u25cf Awake \u00b7 direct link", C["mintd"]
        else:
            st, col = f"\u25cf Awake \u00b7 via {p['via']}", C["lavd"]
        tk.Label(body, text=st, font=MONO, bg=bg, fg=col, anchor="w").pack(fill="x")

        r3 = tk.Frame(body, bg=bg)
        r3.pack(fill="x")
        if last:
            pv = ("You: " if last["dir"] == "out" else "") + last["payload"]
            if len(pv) > 22:
                pv = pv[:21] + "\u2026"
        else:
            pv = f"{p['ip']}:{p['port']}" if p["direct"] else "learned via routing"
        tk.Label(r3, text=pv, font=("Consolas", 8, "italic" if last else "normal"), bg=bg, fg=C["mute"],
                 anchor="w").pack(side="left")
        if unread:
            pill(r3, "NEW", "white", C["coral"], border=C["coral"], font=("Consolas", 8, "bold")).pack(side="right")
        bind_click(w, lambda e, pid=p["id"]: self.select(pid))

    def render_me(self):
        s = self.state
        if self.me_sig == (s["me"], s["port"]):
            return
        self.me_sig = (s["me"], s["port"])
        bg = C["mint"]
        for w in self.me_frame.winfo_children():
            w.destroy()
        creature(self.me_frame, s["me"], 44, True, bg, me=True).pack(side="left", padx=10, pady=8)
        b = tk.Frame(self.me_frame, bg=bg)
        b.pack(side="left")
        tk.Label(b, text=f"You (Peer {s['me']}) \u273f", font=HEAD, bg=bg, fg=C["ink"]).pack(anchor="w")
        tk.Label(b, text=f"port: {s['port']} \u00b7 awake", font=MONO, bg=bg, fg=C["ink"]).pack(anchor="w")
        pill(self.me_frame, "ONLINE", C["ink"], C["white"], border=C["ink"], padx=10, pady=3).pack(
            side="right", padx=12)

    def render_top(self):
        p = self.peer_by_id(self.selected)
        if not p:
            return
        sig = (p["id"], p["reachable"], p["via"], p["cost"])
        if sig == self.top_sig:
            return
        self.top_sig = sig
        for w in self.top.winfo_children():
            w.destroy()
        creature(self.top, p["id"], 44, p["reachable"], C["white"]).pack(side="left", padx=(16, 10), pady=12)
        b = tk.Frame(self.top, bg=C["white"])
        b.pack(side="left")
        tk.Label(b, text=f"Peer {p['id']}", font=BIG, bg=C["white"], fg=C["ink"]).pack(anchor="w")
        tk.Label(b, text=self.link_label(p), font=MONO, bg=C["white"], fg=C["mute"]).pack(anchor="w")
        chunky(self.top, C["white"], "Traceroute", C["white"], C["ink"], self.traceroute, padx=12, pady=5, shadow=2)[0].pack(
            side="right", padx=16)

    def render_thread(self):
        msgs = self.msgs_for(self.selected) if self.selected else []
        sig = (self.selected, tuple((m["n"], m["status"] if m["dir"] == "out" else None) for m in msgs))
        if sig == self.thread_sig:
            return
        self.thread_sig = sig
        t = self.thread
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not msgs:
            t.insert("end", "\n\n", "center")
            t.insert("end", f"No messages with Peer {self.selected} yet.\nSay hello below!", "banner")
            t.configure(state="disabled")
            return

        last_date = None
        for m in msgs:
            dt = time.strftime("%B %d", time.localtime(m["ts"]))
            if dt != last_date:
                last_date = dt
                t.insert("end", f"\u2014 {dt} \u2014\n", "date")

            if m["dir"] == "in":
                t.insert("end", f"Peer {m['peer']} \u00b7 {fmt(m['ts'])}\n", "in_meta")
                bubble_tag = "in_bubble"
                if m.get("dropped"):
                    text = f"[CRC FAILED & DROPPED] {m['payload']}"
                    bubble_tag = "in_bubble bad_bubble"
                else:
                    text = m["payload"]
                t.insert("end", f" {text} \n", bubble_tag)
                t.insert("end", "\n", "center")
            else:
                st = m["status"]
                ret = m["retries"]
                if st == "delivered":
                    chip_tag, chip_text = "chip_ok", "\u2713 Delivered"
                elif st == "sent":
                    chip_text = f"\u21bb Retrying ({ret}/{peer.MAX_RETRIES})" if ret else "\u2022 Sending..."
                    chip_tag = "chip_bad" if ret else "chip"
                else:
                    chip_tag, chip_text = "chip_bad", f"\u2715 Failed ({ret} retries)"
                t.insert("end", f"{fmt(m['ts'])} \u00b7 You  \n", "out_meta")
                t.insert("end", f" {m['payload']} \n", "out_bubble")
                t.insert("end", " ", "out_chips")
                t.insert("end", chip_text, chip_tag)
                if m.get("corrupted"):
                    t.insert("end", "  [CRC CORRUPTED]", "note")
                t.insert("end", "\n\n", "center")
        t.configure(state="disabled")
        t.see("end")

    def render_composer(self):
        p = self.peer_by_id(self.selected)
        reachable = p and p["reachable"]
        state = "normal" if reachable else "disabled"
        self.entry.configure(state=state)
        bg = C["white"] if reachable else C["bg"]
        self.entry.configure(background=bg)
        self.ph.configure(background=bg)
        self.send_btn.configure(state=state)
        if not reachable:
            self.ph.place_forget()
        else:
            self.update_ph()
        if self.corrupt:
            self.tamper.configure(bg=C["pink"], fg=C["pinkd"])
            self.hint.configure(text="Next msg CRC will be broken!")
            self.hint.pack(side="left", padx=(10, 0))
        else:
            self.tamper.configure(bg=C["yellow"], fg=C["ink"])
            self.hint.pack_forget()


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def main():
    args = peer.parse_args()
    neighbours = peer.load_peer_table(args.config, args.id)

    root = tk.Tk()

    # Enable Windows high-DPI awareness
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # Automatically set Tkinter's native scaling factor based on display DPI
    dpi = root.winfo_fpixels('1i')
    root.tk.call('tk', 'scaling', dpi / 72.0)

    global SCALE
    SCALE = max(1.0, dpi / 96.0)

    node = GuiNode(args.id, args.port, neighbours)
    
    # Redirect standard listener connection handler to the GUI-aware version
    peer.handle_connection = gui_handle_connection
    
    server = peer.start_listener(args.port, node)
    node.start_background()

    app = App(root, node)
    try:
        root.mainloop()
    finally:
        node.running = False
        server.close()


if __name__ == "__main__":
    main()