"""
echokivy.py - Dynamic Mobile front-end for peer.py, "creature mesh" theme.

Features:
  - 100% Procedural Vector Icons: No missing font glyphs, tofu boxes, or emoji errors.
  - Dynamically adapts to any mobile screen dimensions and densities (dp/sp).
  - Neo-brutalist sticker theme with hard offset drop-shadows and ink outlines.
  - Procedural mascot avatars ("Creatures") with live status presence dots.
  - Mobile 2-screen navigation (ScreenManager: Companions Hub <-> Chat View).
  - Full backend parity with lan_chat_tk.py (Distance Vector, ACKs, CRC checks, heartbeats).

Run:
    python echokivy.py --id A --port 5001 --config peers.json
"""

import sys
import os
import time
import re
import queue
import threading
import argparse

# Kivy Configuration
os.environ["KIVY_NO_ARGS"] = "1"  # Prevent Kivy from consuming custom CLI args

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.graphics import Color, RoundedRectangle, Line, Ellipse, Triangle, Bezier


# ============================================================================
# PEER BACKEND IMPORT / STANDALONE FALLBACK
# ============================================================================
try:
    import peer
except ImportError:
    import socket, uuid, zlib, json
    class DummyPeer:
        DEFAULT_TTL = 5
        REQUIRED_FIELDS = ("id", "type", "src", "dst", "payload", "hops", "ttl", "crc")
        CONNECT_TIMEOUT = 3
        HEARTBEAT_TIMEOUT = 1
        HEARTBEAT_INTERVAL = 2
        DEAD_AFTER = 6
        DV_INTERVAL = 5
        INFINITY = 16
        ACK_TIMEOUT = 3
        MAX_RETRIES = 3
        @staticmethod
        def compute_crc(msg):
            body = {k: v for k, v in msg.items() if k not in ("crc", "hops", "ttl")}
            text = json.dumps(body, sort_keys=True, separators=(",", ":"))
            return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF
        @staticmethod
        def build_message(src, dst, payload, msg_type="chat", ttl=5):
            msg = {"id": str(uuid.uuid4()), "type": msg_type, "src": src, "dst": dst,
                   "payload": payload, "hops": 0, "ttl": ttl}
            msg["crc"] = DummyPeer.compute_crc(msg)
            return msg
        @staticmethod
        def serialize(msg): return json.dumps(msg) + "\n"
        @staticmethod
        def parse(line):
            try: return json.loads(line)
            except Exception: return None
        @staticmethod
        def verify_crc(msg): return DummyPeer.compute_crc(msg) == msg.get("crc")
        @staticmethod
        def send_to_peer(peer_info, data, timeout=3):
            try:
                with socket.create_connection((peer_info["ip"], peer_info["port"]), timeout=timeout) as s:
                    s.sendall(data.encode("utf-8"))
                return True, ""
            except OSError as e: return False, str(e)
        class Node:
            def __init__(self, my_id, port, neighbours):
                self.id, self.port, self.neighbours = my_id, port, neighbours
                self.lock, self.trigger, self.running = threading.RLock(), threading.Event(), True
                self.pending, self.outbox, self.seen = {}, [], set()
                self.routes = {my_id: {"next": my_id, "cost": 0}}
                for nid in neighbours: self.routes[nid] = {"next": nid, "cost": 1}
            def start_background(self): pass
            def next_hop(self, dst): return self.routes.get(dst, {}).get("next")
            def send_chat(self, dst, text): return None
        @staticmethod
        def parse_args():
            p = argparse.ArgumentParser()
            p.add_argument("--id", default="A")
            p.add_argument("--port", default=5001, type=int)
            p.add_argument("--config", default="peers.json")
            return p.parse_args()
        @staticmethod
        def load_peer_table(path, my_id):
            if os.path.exists(path):
                with open(path) as f: return {e["id"]: e for e in json.load(f).get(my_id, [])}
            return {"B": {"id": "B", "ip": "127.0.0.1", "port": 5002, "status": "up"}}
        @staticmethod
        def start_listener(port, node): return None
    peer = DummyPeer


# ============================================================================
# COLOR PALETTE
# ============================================================================
HEX_COLORS = {
    "bg": "#fff8ec", "ink": "#2a2840", "mute": "#8a8799", "white": "#ffffff",
    "pink": "#ffe1e5", "pinkd": "#d93a4f", "coral": "#f4646f", "coral_d": "#e2475a",
    "mint": "#d9f6e8", "mintd": "#16805a", "yellow": "#ffd75e", "yellow_l": "#fff1b8",
    "lav": "#ece7ff", "lavd": "#5b47c9", "sky": "#d8ecff", "skyd": "#2c5f9e",
    "sel": "#fff0f2", "code": "#f6f1e3", "up": "#2fbf80", "off": "#f0566a"
}

PALETTE = ["#ffd9a8", "#c9f0dc", "#d9ccff", "#ffc9d6", "#bfe3ff", "#fff0a8"]

def c_rgba(hex_code, alpha=1.0):
    hex_code = hex_code.lstrip("#")
    return (int(hex_code[0:2], 16) / 255.0,
            int(hex_code[2:4], 16) / 255.0,
            int(hex_code[4:6], 16) / 255.0,
            alpha)

C = {k: c_rgba(v) for k, v in HEX_COLORS.items()}
Window.clearcolor = C["bg"]


# ============================================================================
# HARDWARE-ACCELERATED PROCEDURAL VECTOR ICONS
# ============================================================================
class VectorIcon(Widget):
    """Draws pixel-perfect vector icons on Kivy Canvas with zero font dependencies."""
    def __init__(self, icon_name="dot", icon_color=None, size_dp=16, **kwargs):
        super().__init__(**kwargs)
        self.icon_name = icon_name
        self.icon_color = icon_color or C["ink"]
        self.size_hint = (None, None)
        self.size = (dp(size_dp), dp(size_dp))
        self.bind(pos=self.redraw, size=self.redraw)
        self.redraw()

    def set_color(self, color):
        self.icon_color = color
        self.redraw()

    def redraw(self, *args):
        self.canvas.clear()
        with self.canvas:
            w, h = self.width, self.height
            x, y = self.x, self.y
            Color(*self.icon_color)

            if self.icon_name == "logo_dot":
                # Golden yellow round emblem with ink outline & highlight
                Color(*C["yellow"])
                Ellipse(pos=(x + dp(1), y + dp(1)), size=(w - dp(2), h - dp(2)))
                Color(*C["ink"])
                Line(ellipse=(x + dp(1), y + dp(1), w - dp(2), h - dp(2)), width=dp(1.3))
                Color(*C["white"])
                Ellipse(pos=(x + w * 0.28, y + h * 0.52), size=(w * 0.28, h * 0.28))

            elif self.icon_name == "back":
                # Crisp left chevron <
                Color(*self.icon_color)
                Line(points=[x + w * 0.65, y + h * 0.82,
                             x + w * 0.30, y + h * 0.50,
                             x + w * 0.65, y + h * 0.18],
                     width=dp(2.2), cap='round', joint='round')

            elif self.icon_name == "send":
                # Paper-airplane style arrowhead
                Color(*self.icon_color)
                Triangle(points=[x + w * 0.15, y + h * 0.88,
                                 x + w * 0.88, y + h * 0.50,
                                 x + w * 0.15, y + h * 0.12])
                Color(*C["ink"])
                Line(points=[x + w * 0.15, y + h * 0.88,
                             x + w * 0.88, y + h * 0.50,
                             x + w * 0.15, y + h * 0.12,
                             x + w * 0.35, y + h * 0.50,
                             x + w * 0.15, y + h * 0.88], width=dp(1.2))

            elif self.icon_name == "heart":
                # Cute filled heart
                Color(*self.icon_color)
                rw = w * 0.44
                Ellipse(pos=(x + w * 0.08, y + h * 0.40), size=(rw, rw))
                Ellipse(pos=(x + w * 0.48, y + h * 0.40), size=(rw, rw))
                Triangle(points=[x + w * 0.09, y + h * 0.55,
                                 x + w * 0.91, y + h * 0.55,
                                 x + w * 0.50, y + h * 0.10])

            elif self.icon_name == "check":
                # Green checkmark
                Color(*self.icon_color)
                Line(points=[x + w * 0.15, y + h * 0.48,
                             x + w * 0.42, y + h * 0.20,
                             x + w * 0.88, y + h * 0.82],
                     width=dp(2.0), cap='round', joint='round')

            elif self.icon_name == "retry":
                # Rotating refresh arrow
                Color(*self.icon_color)
                Line(circle=(x + w * 0.5, y + h * 0.5, w * 0.35, 45, 315),
                     width=dp(1.8), cap='round')
                Triangle(points=[x + w * 0.65, y + h * 0.88,
                                 x + w * 0.92, y + h * 0.65,
                                 x + w * 0.60, y + h * 0.55])

            elif self.icon_name == "cross":
                # Red X mark
                Color(*self.icon_color)
                Line(points=[x + w * 0.2, y + h * 0.2, x + w * 0.8, y + h * 0.8],
                     width=dp(2.0), cap='round')
                Line(points=[x + w * 0.2, y + h * 0.8, x + w * 0.8, y + h * 0.2],
                     width=dp(2.0), cap='round')

            elif self.icon_name == "moon":
                # Crescent moon
                Color(*C["yellow"])
                Ellipse(pos=(x + w * 0.1, y + h * 0.1), size=(w * 0.8, h * 0.8))
                Color(*C["sel"])  # Cutout with background color
                Ellipse(pos=(x + w * 0.32, y + h * 0.25), size=(w * 0.7, h * 0.7))
                Color(*C["ink"])
                Line(circle=(x + w * 0.5, y + h * 0.5, w * 0.38, 80, 280), width=dp(1.2))

            elif self.icon_name == "star":
                # Star / spark emblem
                Color(*self.icon_color)
                Line(points=[x + w * 0.5, y + h * 0.1, x + w * 0.5, y + h * 0.9], width=dp(1.8))
                Line(points=[x + w * 0.1, y + h * 0.5, x + w * 0.9, y + h * 0.5], width=dp(1.8))
                Line(points=[x + w * 0.25, y + h * 0.25, x + w * 0.75, y + h * 0.75], width=dp(1.4))
                Line(points=[x + w * 0.25, y + h * 0.75, x + w * 0.75, y + h * 0.25], width=dp(1.4))


# ============================================================================
# PROCEDURAL MASCOT CREATURES
# ============================================================================
class CreatureWidget(Widget):
    """Procedurally drawn mascot avatar matching echotk."""
    def __init__(self, peer_id="A", size_dp=42, awake=True, is_me=False, show_dot=True, **kwargs):
        super().__init__(**kwargs)
        self.peer_id = peer_id
        self.awake = awake
        self.is_me = is_me
        self.show_dot = show_dot
        self.size_hint = (None, None)
        self.size = (dp(size_dp), dp(size_dp))
        self.bind(pos=self.redraw, size=self.redraw)
        self.redraw()

    def update_state(self, awake):
        if self.awake != awake:
            self.awake = awake
            self.redraw()

    def redraw(self, *args):
        self.canvas.clear()
        with self.canvas:
            s = min(self.width, self.height)
            x, y = self.x + (self.width - s) / 2, self.y + (self.height - s) / 2

            idx = sum(ord(ch) for ch in str(self.peer_id)) % len(PALETTE)
            body_color = c_rgba(PALETTE[idx])
            ink = C["ink"]

            if self.is_me:
                # Antenna
                Color(*ink)
                Line(points=[x + s * 0.5, y + s * 0.75, x + s * 0.5, y + s * 0.92], width=dp(2))
                Color(*C["coral"])
                Ellipse(pos=(x + s * 0.42, y + s * 0.86), size=(s * 0.16, s * 0.16))
                Color(*ink)
                Line(ellipse=(x + s * 0.42, y + s * 0.86, s * 0.16, s * 0.16), width=dp(1.3))
            else:
                # Ears
                for ex in (0.24, 0.76):
                    Color(*body_color)
                    Ellipse(pos=(x + s * (ex - 0.11), y + s * 0.66), size=(s * 0.22, s * 0.22))
                    Color(*ink)
                    Line(ellipse=(x + s * (ex - 0.11), y + s * 0.66, s * 0.22, s * 0.22), width=dp(1.4))

            # Main head/body
            Color(*body_color)
            RoundedRectangle(pos=(x + s * 0.1, y + s * 0.1), size=(s * 0.8, s * 0.7), radius=[s * 0.2])
            Color(*ink)
            Line(rounded_rectangle=(x + s * 0.1, y + s * 0.1, s * 0.8, s * 0.7, s * 0.2), width=dp(1.5))

            # Cheeks
            Color(*c_rgba("#ff9fb0"))
            for ex in (0.24, 0.76):
                Ellipse(pos=(x + s * (ex - 0.06), y + s * 0.32), size=(s * 0.12, s * 0.08))

            # Eyes & Expression
            Color(*ink)
            if self.awake:
                r = s * 0.06
                for ex in (0.34, 0.66):
                    Ellipse(pos=(x + s * ex - r, y + s * 0.46 - r), size=(r * 2, r * 2))
                Line(circle=(x + s * 0.5, y + s * 0.45, s * 0.14, 200, 340), width=dp(1.5))
            else:
                for ex in (0.34, 0.66):
                    Line(circle=(x + s * ex, y + s * 0.48, s * 0.08, 20, 160), width=dp(1.5))
                Ellipse(pos=(x + s * 0.47, y + s * 0.30), size=(s * 0.06, s * 0.06))
                Color(*C["lav"])
                Triangle(points=[x + s * 0.2, y + s * 0.7, x + s * 0.8, y + s * 0.7, x + s * 0.62, y + s * 0.96])
                Color(*ink)
                Line(points=[x + s * 0.2, y + s * 0.7, x + s * 0.62, y + s * 0.96, x + s * 0.8, y + s * 0.7], width=dp(1.3))
                Color(*C["white"])
                Ellipse(pos=(x + s * 0.55, y + s * 0.90), size=(s * 0.14, s * 0.14))
                Color(*ink)
                Line(ellipse=(x + s * 0.55, y + s * 0.90, s * 0.14, s * 0.14), width=dp(1.2))

            # Live status dot
            if self.show_dot:
                dot_size = s * 0.28
                dot_x, dot_y = x + s - dot_size, y + s * 0.08
                Color(*C["white"])
                Ellipse(pos=(dot_x - dp(1.5), dot_y - dp(1.5)), size=(dot_size + dp(3), dot_size + dp(3)))
                Color(*(C["up"] if self.awake else C["off"]))
                Ellipse(pos=(dot_x, dot_y), size=(dot_size, dot_size))


# ============================================================================
# NEO-BRUTALIST STICKER CARDS & BUTTONS
# ============================================================================
class StickerCard(BoxLayout):
    def __init__(self, bg_color=C["white"], shadow_color=C["ink"],
                 shadow_offset=None, radius=None, border_width=None, **kwargs):
        super().__init__(**kwargs)
        self.bg_color = bg_color
        self.shadow_color = shadow_color
        self.shadow_offset = dp(3) if shadow_offset is None else dp(shadow_offset)
        self.radius = dp(6) if radius is None else dp(radius)
        self.border_width = dp(1.5) if border_width is None else dp(border_width)

        with self.canvas.before:
            self.c_shadow = Color(*self.shadow_color)
            self.rect_shadow = RoundedRectangle(radius=[self.radius])
            self.c_bg = Color(*self.bg_color)
            self.rect_bg = RoundedRectangle(radius=[self.radius])
            self.c_border = Color(*C["ink"])
            self.border_line = Line(width=self.border_width)

        self.bind(pos=self._update_shape, size=self._update_shape)

    def set_bg(self, color):
        self.bg_color = color
        self.c_bg.rgba = color

    def _update_shape(self, *args):
        so = self.shadow_offset
        self.rect_shadow.pos = (self.x + so, self.y - so)
        self.rect_shadow.size = self.size
        self.rect_bg.pos = self.pos
        self.rect_bg.size = self.size
        self.border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, self.radius)


class ChunkyButton(Button):
    def __init__(self, bg_color=C["white"], text_color=C["ink"],
                 shadow_offset=None, radius=None, **kwargs):
        super().__init__(**kwargs)
        self.bg_color = bg_color
        self.base_text_color = text_color
        self.shadow_offset = dp(3) if shadow_offset is None else dp(shadow_offset)
        self.radius = dp(5) if radius is None else dp(radius)
        self.background_color = (0, 0, 0, 0)
        self.color = text_color
        self.bold = True
        self.font_size = sp(11)

        with self.canvas.before:
            self.c_shadow = Color(*C["ink"])
            self.rect_shadow = RoundedRectangle(radius=[self.radius])
            self.c_bg = Color(*self.bg_color)
            self.rect_bg = RoundedRectangle(radius=[self.radius])
            self.c_border = Color(*C["ink"])
            self.border_line = Line(width=dp(1.4))

        self.bind(pos=self._update_geom, size=self._update_geom, state=self._on_state)

    def set_bg(self, color, fg_color=None):
        self.bg_color = color
        self.c_bg.rgba = color
        if fg_color:
            self.color = fg_color

    def _on_state(self, instance, state):
        if state == 'down':
            self.rect_bg.pos = (self.x + dp(2), self.y - dp(2))
            self.border_line.rounded_rectangle = (self.x + dp(2), self.y - dp(2), self.width, self.height, self.radius)
        else:
            self._update_geom()

    def _update_geom(self, *args):
        so = self.shadow_offset
        self.rect_shadow.pos = (self.x + so, self.y - so)
        self.rect_shadow.size = self.size
        self.rect_bg.pos = self.pos
        self.rect_bg.size = self.size
        self.border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, self.radius)


class StatusPill(BoxLayout):
    def __init__(self, text="", fg_color=C["ink"], bg_color=C["mint"],
                 border_color=C["ink"], icon_type=None, **kwargs):
        super().__init__(orientation='horizontal', spacing=dp(4), **kwargs)
        self.size_hint = (None, None)
        self.padding = [dp(6), dp(2), dp(6), dp(2)]
        self.height = dp(20)

        with self.canvas.before:
            self.c_bg = Color(*bg_color)
            self.rect = RoundedRectangle(radius=[dp(3)])
            self.c_border = Color(*border_color)
            self.line = Line(rounded_rectangle=(0, 0, 0, 0, dp(3)), width=dp(1))

        if icon_type:
            self.icon = VectorIcon(icon_name=icon_type, icon_color=fg_color, size_dp=12)
            self.add_widget(self.icon)
        else:
            self.icon = None

        self.lbl = Label(text=text, color=fg_color, font_size=sp(9), bold=True)
        self.lbl.bind(texture_size=self._on_txt)
        self.add_widget(self.lbl)
        self.bind(pos=self._update, size=self._update)

    def _on_txt(self, *args):
        extra = dp(20) if self.icon else dp(14)
        self.width = max(self.lbl.texture_size[0] + extra, dp(28))

    def set_data(self, text, fg=None, bg=None):
        self.lbl.text = text
        if fg:
            self.lbl.color = fg
            if self.icon: self.icon.set_color(fg)
        if bg: self.c_bg.rgba = bg

    def _update(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size
        self.line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(3))


# ============================================================================
# GUINODE (Backend Logic)
# ============================================================================
class GuiNode(peer.Node):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log = []
        self.log_lock = threading.Lock()
        self.counter = 0
        self.sent_at = {}
        self.last_rtt = None
        self.last_rtt_ts = 0
        self.plain = {}   # msg id -> readable text for my own view

    def add(self, rec):
        with self.log_lock:
            self.counter += 1
            rec["n"] = self.counter
            self.log.append(rec)
        return rec

    def say(self, text):
        for line in text.split("\n"):
            m = re.match(r"\[LINK (UP|DOWN)\] (?:no heartbeat from )?(\S+)", line)
            if m and m.group(2) in self.neighbours:
                self.add({"dir": "sys", "kind": m.group(1).lower(), "peer": m.group(2),
                          "payload": line, "ts": time.time()})

    def handle_ack(self, msg):
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
        hop = self.next_hop(dst)
        if hop is None:
            return f"No route to {dst}"
        msg = peer.build_message(self.id, dst, peer.encrypt_text(text))
        if corrupt:
            msg["crc"] ^= 1
        entry = {"msg": msg, "dst": dst, "text": text, "status": "SENT",
                 "retries": 0, "deadline": time.time() + getattr(peer, 'ACK_TIMEOUT', 3)}
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
    try:
        remote_ip = conn.getpeername()[0]
    except OSError:
        remote_ip = None
    with conn:
        try:
            reader = conn.makefile("r", encoding="utf-8")
            for line in reader:
                line = line.strip()
                if not line: continue
                msg = peer.parse(line)
                if msg is None: continue
                if not peer.verify_crc(msg):
                    if msg["type"] == "chat" and msg["dst"] == node.id:
                        node.add({"dir": "in", "peer": msg["src"], "payload": str(msg["payload"]),
                                  "ts": time.time(), "dropped": True, "crc_ok": False,
                                  "fields": dict(msg)})
                    continue
                # Learn a known neighbour's IP from where its heartbeat/dv came from
                if remote_ip and msg["type"] in ("heartbeat", "dv"):
                    with node.lock:
                        n = node.neighbours.get(msg["src"])
                        if n is not None and n.get("ip") != remote_ip:
                            n["ip"] = remote_ip
                node.handle_message(msg)
        except (OSError, UnicodeDecodeError):
            return


# ============================================================================
# COMPANION CARD
# ============================================================================
class CompanionItem(StickerCard):
    def __init__(self, peer_data, is_selected=False, on_select=None, **kwargs):
        bg = C["sel"] if is_selected else C["white"]
        super().__init__(bg_color=bg, shadow_offset=3, radius=6, orientation='horizontal',
                         padding=[dp(8), dp(6), dp(8), dp(6)], spacing=dp(8),
                         size_hint=(1, None), height=dp(68), **kwargs)
        self.peer_data = peer_data
        self.on_select = on_select

        if is_selected:
            sel_bar = Widget(size_hint=(None, 1), width=dp(4))
            with sel_bar.canvas:
                Color(*C["coral"])
                RoundedRectangle(pos=sel_bar.pos, size=sel_bar.size, radius=[dp(2)])
            sel_bar.bind(pos=lambda w, p: setattr(sel_bar.canvas.children[-1], 'pos', p),
                         size=lambda w, s: setattr(sel_bar.canvas.children[-1], 'size', s))
            self.add_widget(sel_bar)

        self.avatar = CreatureWidget(peer_id=peer_data["id"], size_dp=44, awake=peer_data["reachable"])
        self.add_widget(self.avatar)

        info = BoxLayout(orientation='vertical', size_hint=(1, 1), spacing=dp(2))

        # Row 1: Peer Name + Status Badge
        r1 = BoxLayout(size_hint=(1, 0.45), spacing=dp(4))
        name_box = BoxLayout(orientation='horizontal', size_hint=(1, 1), spacing=dp(4))
        name_lbl = Label(text=f"[b]Peer {peer_data['id']}[/b]", markup=True,
                         color=C["ink"], font_size=sp(12.5), halign="left", valign="middle")
        name_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        name_box.add_widget(name_lbl)
        if not peer_data["reachable"]:
            name_box.add_widget(VectorIcon(icon_name="moon", size_dp=12))
        r1.add_widget(name_box)

        if not peer_data["reachable"]:
            badge = StatusPill("UNREACHABLE", fg_color=C["pinkd"], bg_color=C["pink"])
        elif peer_data["via"] == peer_data["id"]:
            badge = StatusPill("ACTIVE", fg_color=C["mintd"], bg_color=C["mint"])
        else:
            badge = StatusPill(f"VIA {peer_data['via']}", fg_color=C["lavd"], bg_color=C["lav"])
        r1.add_widget(badge)
        info.add_widget(r1)

        # Row 2: Subtitle status
        if not peer_data["reachable"]:
            sub = "Asleep (link down)" if peer_data["direct"] else "Asleep (no route)"
            sub_col = C["pinkd"]
        elif peer_data["via"] == peer_data["id"]:
            sub = "Awake (direct link)"
            sub_col = C["mintd"]
        else:
            sub = f"Awake (via {peer_data['via']})"
            sub_col = C["lavd"]

        sub_lbl = Label(text=sub, color=sub_col, font_size=sp(9.5), halign="left",
                        size_hint=(1, 0.28), shorten=True, shorten_from="right")
        sub_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        info.add_widget(sub_lbl)

        # Row 3: Preview snippet
        preview = peer_data.get("last_preview", f"{peer_data['ip']}:{peer_data['port']}")
        r3 = BoxLayout(size_hint=(1, 0.27))
        prev_lbl = Label(text=preview, color=C["mute"], font_size=sp(9), halign="left",
                         size_hint=(1, 1), shorten=True, shorten_from="right")
        prev_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        r3.add_widget(prev_lbl)
        if peer_data.get("unread"):
            r3.add_widget(StatusPill("NEW", fg_color=C["white"], bg_color=C["coral"]))
        info.add_widget(r3)

        self.add_widget(info)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos):
            if self.on_select:
                self.on_select(self.peer_data["id"])
            return True
        return super().on_touch_up(touch)


# ============================================================================
# SCREEN 1: COMPANIONS HUB SCREEN
# ============================================================================
class CompanionsScreen(Screen):
    def __init__(self, app_core, **kwargs):
        super().__init__(**kwargs)
        self.app_core = app_core
        root = BoxLayout(orientation='vertical', padding=[dp(10), dp(8), dp(10), dp(8)], spacing=dp(8))

        # 1. TOP HEADER BAR
        top_bar = StickerCard(bg_color=C["white"], shadow_offset=3, radius=6,
                              size_hint=(1, None), height=dp(52), padding=[dp(8), dp(4), dp(8), dp(4)], spacing=dp(8))
        self.me_avatar = CreatureWidget(peer_id=app_core.node.id, size_dp=38, awake=True, is_me=True, show_dot=False)
        top_bar.add_widget(self.me_avatar)

        title_box = BoxLayout(orientation='vertical', size_hint=(1, 1), spacing=0)
        t_row = BoxLayout(orientation='horizontal', spacing=dp(5))
        t_row.add_widget(VectorIcon(icon_name="logo_dot", size_dp=14))
        t_lbl = Label(text="[b]ECHO[/b] [color=#8a8799]· lan pals[/color]",
                      markup=True, color=C["ink"], font_size=sp(13.5), halign="left")
        t_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        t_row.add_widget(t_lbl)
        title_box.add_widget(t_row)

        sub_t_lbl = Label(text="creature-mesh mobile", color=C["mute"], font_size=sp(9), halign="left")
        sub_t_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        title_box.add_widget(sub_t_lbl)
        top_bar.add_widget(title_box)

        self.pulse_badge = StatusPill("Pulse: --", fg_color=C["pinkd"], bg_color=C["pink"], icon_type="heart")
        top_bar.add_widget(self.pulse_badge)
        root.add_widget(top_bar)

        # 2. METRICS PILLS ROW
        metrics_row = BoxLayout(size_hint=(1, None), height=dp(26), spacing=dp(6))
        self.awake_pill = StatusPill("Awake: 0/0", fg_color=C["ink"], bg_color=C["lav"])
        self.port_pill = StatusPill(f"Broadcast: :{app_core.node.port}", fg_color=C["ink"], bg_color=C["yellow_l"])
        metrics_row.add_widget(self.awake_pill)
        metrics_row.add_widget(self.port_pill)
        root.add_widget(metrics_row)

        # 3. MESH COMPANIONS & SNIFF BAR
        comp_bar = BoxLayout(size_hint=(1, None), height=dp(32), spacing=dp(6))
        title_comp = Label(text="[b]MESH COMPANIONS[/b]", markup=True, color=C["skyd"],
                           font_size=sp(11), halign="left", size_hint=(1, 1))
        title_comp.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        comp_bar.add_widget(title_comp)

        self.count_pill = StatusPill("0 BOTS", fg_color=C["ink"], bg_color=C["yellow"])
        comp_bar.add_widget(self.count_pill)

        sniff_btn = ChunkyButton(text="+ Sniff LAN", bg_color=C["white"], text_color=C["ink"],
                                 size_hint=(None, 1), width=dp(94))
        sniff_btn.bind(on_press=lambda inst: self.app_core.sniff())
        comp_bar.add_widget(sniff_btn)
        root.add_widget(comp_bar)

        # 4. TABS ROW
        tab_box = StickerCard(bg_color=C["white"], shadow_offset=2, radius=4,
                              size_hint=(1, None), height=dp(34), padding=[dp(2), dp(2), dp(2), dp(2)], spacing=dp(4))
        self.tab_btns = {}
        for tab_key, tab_title in (("all", "All"), ("direct", "Direct"), ("multi", "Multi-hop")):
            btn = Button(text=tab_title, font_size=sp(10.5), bold=True, background_color=(0,0,0,0),
                         color=C["ink"])
            btn.bind(on_press=lambda inst, k=tab_key: self.app_core.set_tab(k))
            self.tab_btns[tab_key] = btn
            tab_box.add_widget(btn)
        root.add_widget(tab_box)

        # 5. SCROLLABLE COMPANION LIST
        self.scroll = ScrollView(size_hint=(1, 1), bar_width=dp(4))
        self.list_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(8),
                                     padding=[dp(2), dp(4), dp(2), dp(4)])
        self.list_layout.bind(minimum_height=self.list_layout.setter('height'))
        self.scroll.add_widget(self.list_layout)
        root.add_widget(self.scroll)

        # 6. BOTTOM "YOU" CARD
        you_card = StickerCard(bg_color=C["mint"], shadow_offset=3, radius=6,
                               size_hint=(1, None), height=dp(48), padding=[dp(8), dp(4), dp(8), dp(4)], spacing=dp(8))
        you_avatar = CreatureWidget(peer_id=app_core.node.id, size_dp=36, awake=True, is_me=True, show_dot=False)
        you_card.add_widget(you_avatar)

        y_info = BoxLayout(orientation='vertical', size_hint=(1, 1), spacing=0)
        y_title = Label(text=f"[b]You (Peer {app_core.node.id})[/b]", markup=True,
                        color=C["ink"], font_size=sp(11), halign="left")
        y_title.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        y_sub = Label(text=f"port: {app_core.node.port} · awake", color=C["ink"],
                      font_size=sp(9), halign="left")
        y_sub.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        y_info.add_widget(y_title)
        y_info.add_widget(y_sub)
        you_card.add_widget(y_info)

        you_card.add_widget(StatusPill("ONLINE", fg_color=C["ink"], bg_color=C["white"], border_color=C["ink"]))
        root.add_widget(you_card)

        self.add_widget(root)

    def update_ui(self, state):
        rtt = self.app_core.node.last_rtt
        if rtt is not None and time.time() - self.app_core.node.last_rtt_ts < 30:
            self.pulse_badge.set_data(f"Pulse: {rtt:.0f}ms")
        else:
            self.pulse_badge.set_data("Pulse: --")

        total = len(state["peers"])
        reach = sum(1 for p in state["peers"] if p["reachable"])
        self.awake_pill.set_data(f"Awake: {reach}/{total}")
        self.count_pill.set_data(f"{total} BOTS")

        for k, b in self.tab_btns.items():
            if k == self.app_core.current_tab:
                b.color = C["white"]
                b.background_color = C["ink"]
            else:
                b.color = C["ink"]
                b.background_color = (0, 0, 0, 0)

        self.list_layout.clear_widgets()
        shown = [p for p in state["peers"]
                 if self.app_core.current_tab == "all"
                 or (self.app_core.current_tab == "direct" and p["direct"])
                 or (self.app_core.current_tab == "multi" and not p["direct"])]

        if not shown:
            msg = "No multi-hop peers learned yet." if self.app_core.current_tab == "multi" else "No companions detected."
            lbl = Label(text=msg, color=C["mute"], font_size=sp(11), size_hint_y=None, height=dp(60))
            self.list_layout.add_widget(lbl)
            return

        for p in shown:
            ms = [m for m in state["messages"] if m["peer"] == p["id"] and m["dir"] != "sys"]
            last = ms[-1] if ms else None
            if last:
                prefix = "You: " if last["dir"] == "out" else ""
                txt = prefix + last["payload"]
                p["last_preview"] = txt[:24] + ("…" if len(txt) > 24 else "")
            else:
                p["last_preview"] = f"{p['ip']}:{p['port']}" if p["direct"] else "learned via routing"

            inc = sum(1 for m in ms if m["dir"] == "in")
            p["unread"] = (p["id"] != self.app_core.selected_peer and inc > self.app_core.seen_in.get(p["id"], 0))

            card = CompanionItem(p, is_selected=(p["id"] == self.app_core.selected_peer),
                                 on_select=self.app_core.open_chat_for)
            self.list_layout.add_widget(card)


# ============================================================================
# CHAT MESSAGE BUBBLE WITH VECTOR DELIVERY CHIPS
# ============================================================================
class MessageBubble(BoxLayout):
    def __init__(self, msg, **kwargs):
        super().__init__(orientation='vertical', size_hint_y=None, spacing=dp(2), **kwargs)
        is_in = msg["dir"] == "in"
        bg_col = C["pink"] if msg.get("dropped") else (C["white"] if is_in else C["yellow_l"])
        card_align = "left" if is_in else "right"

        tm_str = time.strftime("%H:%M", time.localtime(msg["ts"]))
        header_text = f"Peer {msg['peer']} · {tm_str}" if is_in else f"{tm_str} · You"
        hdr_lbl = Label(text=header_text, color=C["mute"], font_size=sp(9),
                        halign=card_align, size_hint_y=None, height=dp(14))
        hdr_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        self.add_widget(hdr_lbl)

        content_box = AnchorLayout(anchor_x=card_align, size_hint_y=None)
        bubble = StickerCard(bg_color=bg_col, shadow_offset=2, radius=6,
                             size_hint=(None, None), padding=[dp(10), dp(8), dp(10), dp(8)])

        body_text = f"[CRC FAILED & DROPPED]\n{msg['payload']}" if msg.get("dropped") else msg['payload']
        msg_lbl = Label(text=body_text, color=C["ink"], font_size=sp(11), halign="left",
                        size_hint=(None, None))
        msg_lbl.bind(texture_size=lambda w, ts: self._resize_bubble(bubble, msg_lbl, ts))
        bubble.add_widget(msg_lbl)
        content_box.add_widget(bubble)
        self.add_widget(content_box)

        # Delivery chip with vector status icon
        if not is_in:
            st = msg.get("status")
            ret = msg.get("retries", 0)
            if st == "delivered":
                chip_txt, chip_col, icon_name = "Delivered", C["mintd"], "check"
            elif st == "sent":
                chip_txt = f"Retrying ({ret}/{getattr(peer, 'MAX_RETRIES', 3)})" if ret else "Sending..."
                chip_col, icon_name = C["mute"], "retry"
            else:
                chip_txt, chip_col, icon_name = f"Failed ({ret} retries)", C["pinkd"], "cross"

            if msg.get("corrupted"):
                chip_txt += "  [CORRUPTED]"
                chip_col = C["pinkd"]

            chip_box = AnchorLayout(anchor_x="right", size_hint_y=None, height=dp(16))
            chip_inner = BoxLayout(orientation='horizontal', spacing=dp(3), size_hint=(None, 1))
            chip_inner.add_widget(VectorIcon(icon_name=icon_name, icon_color=chip_col, size_dp=12))
            chip_lbl = Label(text=chip_txt, color=chip_col, font_size=sp(8.5), bold=True, size_hint=(None, 1))
            chip_lbl.bind(texture_size=lambda w, ts: setattr(w, 'width', ts[0]))
            chip_inner.add_widget(chip_lbl)
            chip_inner.bind(minimum_width=chip_inner.setter('width'))
            chip_box.add_widget(chip_inner)
            self.add_widget(chip_box)
            self.height = dp(70)
        else:
            self.height = dp(56)

    def _resize_bubble(self, bubble, label, texture_size):
        max_w = Window.width * 0.76 if Window.width > dp(100) else dp(260)
        w = min(max(texture_size[0] + dp(22), dp(50)), max_w)
        h = texture_size[1] + dp(16)
        label.size = (w - dp(20), h - dp(16))
        label.text_size = (w - dp(20), None)
        bubble.size = (w, h)


# ============================================================================
# SCREEN 2: CHAT CONVERSATION SCREEN
# ============================================================================
class ChatScreen(Screen):
    def __init__(self, app_core, **kwargs):
        super().__init__(**kwargs)
        self.app_core = app_core
        self.corrupt_crc = False

        root = BoxLayout(orientation='vertical', padding=[dp(8), dp(6), dp(8), dp(6)], spacing=dp(6))

        # 1. TOP CHAT HEADER
        header = StickerCard(bg_color=C["white"], shadow_offset=3, radius=6,
                             size_hint=(1, None), height=dp(54), padding=[dp(6), dp(4), dp(6), dp(4)], spacing=dp(6))

        back_btn = ChunkyButton(bg_color=C["white"], text_color=C["ink"],
                                size_hint=(None, 1), width=dp(38))
        back_btn_box = AnchorLayout(anchor_x='center', anchor_y='center')
        back_btn_box.add_widget(VectorIcon(icon_name="back", icon_color=C["ink"], size_dp=16))
        back_btn.add_widget(back_btn_box)
        back_btn.bind(on_press=lambda inst: self.app_core.go_back_to_companions())
        header.add_widget(back_btn)

        self.chat_avatar = CreatureWidget(peer_id="A", size_dp=38, awake=True)
        header.add_widget(self.chat_avatar)

        title_box = BoxLayout(orientation='vertical', size_hint=(1, 1), spacing=0)
        self.title_lbl = Label(text="[b]Peer --[/b]", markup=True, color=C["ink"],
                               font_size=sp(13), halign="left")
        self.title_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        self.subtitle_lbl = Label(text="...", color=C["mute"], font_size=sp(9),
                                  halign="left")
        self.subtitle_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        title_box.add_widget(self.title_lbl)
        title_box.add_widget(self.subtitle_lbl)
        header.add_widget(title_box)

        trace_btn = ChunkyButton(text="Traceroute", bg_color=C["white"], text_color=C["ink"],
                                 size_hint=(None, 1), width=dp(86))
        trace_btn.bind(on_press=lambda inst: self.app_core.traceroute())
        header.add_widget(trace_btn)
        root.add_widget(header)

        # 2. CHAT THREAD (SCROLLABLE)
        self.scroll = ScrollView(size_hint=(1, 1), bar_width=dp(4))
        self.thread_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(8),
                                       padding=[dp(4), dp(6), dp(4), dp(6)])
        self.thread_layout.bind(minimum_height=self.thread_layout.setter('height'))
        self.scroll.add_widget(self.thread_layout)
        root.add_widget(self.scroll)

        # 3. COMPOSER BAR
        comp_box = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(6))
        input_card = StickerCard(bg_color=C["white"], shadow_offset=2, radius=5,
                                 size_hint=(1, 1), padding=[dp(8), dp(2), dp(8), dp(2)])
        self.input_field = TextInput(hint_text="Say hello...", multiline=False, background_color=(0,0,0,0),
                                     foreground_color=C["ink"], font_size=sp(11.5))
        self.input_field.bind(on_text_validate=lambda inst: self.send_message())
        input_card.add_widget(self.input_field)
        comp_box.add_widget(input_card)

        # Chunky Send Button with vector paper-plane icon
        self.send_btn = ChunkyButton(bg_color=C["coral"], text_color=C["white"],
                                     size_hint=(None, 1), width=dp(74))
        send_inner = BoxLayout(orientation='horizontal', spacing=dp(4), padding=[dp(8), 0, dp(8), 0])
        send_lbl = Label(text="Send", color=C["white"], font_size=sp(11), bold=True)
        send_inner.add_widget(send_lbl)
        send_inner.add_widget(VectorIcon(icon_name="send", icon_color=C["white"], size_dp=12))
        self.send_btn.add_widget(send_inner)
        self.send_btn.bind(on_press=lambda inst: self.send_message())
        comp_box.add_widget(self.send_btn)
        root.add_widget(comp_box)

        # 4. BOT LAB ROW
        lab_box = BoxLayout(size_hint=(1, None), height=dp(30), spacing=dp(6))
        self.corrupt_btn = ChunkyButton(text="Corrupt CRC (demo)", bg_color=C["yellow"], text_color=C["ink"],
                                        size_hint=(0.55, 1))
        self.corrupt_btn.bind(on_press=self.toggle_corrupt)
        lab_box.add_widget(self.corrupt_btn)

        ping_btn = ChunkyButton(text="Force Ping", bg_color=C["white"], text_color=C["ink"],
                                size_hint=(0.45, 1))
        ping_btn.bind(on_press=lambda inst: self.app_core.force_ping())
        lab_box.add_widget(ping_btn)
        root.add_widget(lab_box)

        self.add_widget(root)

    def toggle_corrupt(self, *args):
        self.corrupt_crc = not self.corrupt_crc
        if self.corrupt_crc:
            self.corrupt_btn.set_bg(C["pink"], C["pinkd"])
            self.app_core.toast("Next msg CRC will be broken!")
        else:
            self.corrupt_btn.set_bg(C["yellow"], C["ink"])

    def send_message(self):
        text = self.input_field.text.strip()
        if not text or not self.app_core.selected_peer:
            return
        dst = self.app_core.selected_peer
        corrupt = self.corrupt_crc

        self.input_field.text = ""
        self.corrupt_crc = False
        self.corrupt_btn.set_bg(C["yellow"], C["ink"])

        def work():
            err = self.app_core.node.send_gui(dst, text, corrupt)
            if err:
                self.app_core.toast(err)
        threading.Thread(target=work, daemon=True).start()

    def update_ui(self, state):
        pid = self.app_core.selected_peer
        p = next((x for x in state["peers"] if x["id"] == pid), None)
        if not p:
            return

        self.title_lbl.text = f"[b]Peer {p['id']}[/b]"
        self.subtitle_lbl.text = self.app_core.link_label(p)
        self.chat_avatar.peer_id = p["id"]
        self.chat_avatar.update_state(p["reachable"])

        self.input_field.readonly = not p["reachable"]
        self.send_btn.disabled = not p["reachable"]

        msgs = [m for m in state["messages"] if m["peer"] == pid]
        self.thread_layout.clear_widgets()

        if not msgs:
            empty_lbl = Label(text=f"No messages with Peer {pid} yet.\nSay hello below!",
                              color=C["mute"], font_size=sp(11), halign="center",
                              size_hint_y=None, height=dp(120))
            self.thread_layout.add_widget(empty_lbl)
            return

        for m in msgs:
            if m["dir"] == "sys":
                sys_pill = StatusPill(m["payload"], fg_color=C["mintd"] if m.get("kind") == "up" else C["pinkd"],
                                      bg_color=C["mint"] if m.get("kind") == "up" else C["pink"])
                box = AnchorLayout(anchor_x="center", size_hint_y=None, height=dp(26))
                box.add_widget(sys_pill)
                self.thread_layout.add_widget(box)
            else:
                self.thread_layout.add_widget(MessageBubble(m))


# ============================================================================
# MAIN APPLICATION CONTROLLER
# ============================================================================
class EchoApp(App):
    def __init__(self, node, **kwargs):
        super().__init__(**kwargs)
        self.node = node
        self.selected_peer = None
        self.current_tab = "all"
        self.seen_in = {}
        self.known_extra = set()
        self.toasts = queue.Queue()
        self.state = None

    def build(self):
        self.title = f"Peer {self.node.id} · ECHO Mobile"

        self.root_layout = BoxLayout(orientation='vertical')
        self.sm = ScreenManager(transition=SlideTransition(duration=0.25))

        self.companions_screen = CompanionsScreen(self, name="companions")
        self.chat_screen = ChatScreen(self, name="chat")

        self.sm.add_widget(self.companions_screen)
        self.sm.add_widget(self.chat_screen)
        self.root_layout.add_widget(self.sm)

        # Floating Toast Banner
        self.toast_box = AnchorLayout(anchor_x='center', anchor_y='bottom', padding=[0, 0, 0, dp(70)],
                                      size_hint=(1, None), height=0)
        self.toast_card = StickerCard(bg_color=C["ink"], shadow_offset=2, radius=4,
                                      size_hint=(None, None), height=dp(30), padding=[dp(12), dp(4), dp(12), dp(4)])
        self.toast_lbl = Label(text="", color=C["white"], font_size=sp(9.5), bold=True)
        self.toast_card.add_widget(self.toast_lbl)
        self.toast_box.add_widget(self.toast_card)
        self.toast_box.opacity = 0
        self.root_layout.add_widget(self.toast_box)

        Clock.schedule_interval(self.tick, 0.3)
        return self.root_layout

    def toast(self, msg):
        self.toast_lbl.text = msg
        self.toast_card.width = self.toast_lbl.texture_size[0] + dp(28)
        self.toast_box.opacity = 1
        Clock.unschedule(self._hide_toast)
        Clock.schedule_once(self._hide_toast, 3.0)

    def _hide_toast(self, dt):
        self.toast_box.opacity = 0

    def set_tab(self, tab):
        self.current_tab = tab
        if self.state:
            self.companions_screen.update_ui(self.state)

    def open_chat_for(self, peer_id):
        self.selected_peer = peer_id
        if self.state:
            self.seen_in[peer_id] = sum(1 for m in self.state["messages"]
                                        if m["peer"] == peer_id and m["dir"] == "in")
            self.chat_screen.update_ui(self.state)
        self.sm.transition.direction = "left"
        self.sm.current = "chat"

    def go_back_to_companions(self):
        self.sm.transition.direction = "right"
        self.sm.current = "companions"

    def sniff(self):
        self.node.trigger.set()
        self.toast("Routing update sent to neighbours")

    def force_ping(self):
        for nid, nb in list(self.node.neighbours.items()):
            hb = peer.build_message(self.node.id, nid, "", "heartbeat", ttl=1)
            self.node.send_async(nb, peer.serialize(hb), getattr(peer, 'HEARTBEAT_TIMEOUT', 1))
        self.toast(f"Heartbeat sent to {len(self.node.neighbours)} neighbours")

    def traceroute(self):
        p = next((x for x in self.state["peers"] if x["id"] == self.selected_peer), None) if self.state else None
        if not p:
            self.toast("No companion selected")
        elif not p["reachable"]:
            self.toast(f"No route to Peer {p['id']}")
        elif p["via"] == p["id"]:
            self.toast(f"{self.node.id} → {p['id']} (direct, cost {p['cost']})")
        else:
            self.toast(f"{self.node.id} → {p['via']} → … → {p['id']} (cost {p['cost']})")

    @staticmethod
    def link_label(p):
        if not p["reachable"]:
            return "Unreachable"
        if p["via"] == p["id"]:
            return "Direct link"
        return f"via {p['via']}"

    def build_state(self):
        node = self.node
        inf = getattr(peer, 'INFINITY', 16)
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
                              ip=n.get("ip", ""), port=n.get("port", ""), status=n.get("status", ""),
                              age=time.time() - n.get("last_seen", time.time())))

        self.known_extra.update(d for d in routes if d != node.id and d not in neigh)
        for d in sorted(self.known_extra):
            via, cost = route_info(d)
            peers.append(dict(id=d, direct=False, reachable=via is not None, via=via, cost=cost,
                              ip="", port="", status=""))

        with node.log_lock:
            raw_log = list(node.log)

        msgs = []
        names = {"DELIVERED": "delivered", "SENT": "sent", "FAILED": "failed"}
        for rec in raw_log:
            if rec["dir"] != "out":
                msgs.append(rec)
                continue
            if rec["mid"] in pend:
                st, retries, msg = pend[rec["mid"]]
                status = names.get(st, "sent")
                msgs.append(dict(n=rec["n"], dir="out", peer=rec["peer"], payload=node.plain.get(rec["mid"], msg["payload"]),
                                 ts=rec["ts"], status=status, retries=retries, corrupted=rec.get("corrupted", False),
                                 fields=msg))

        return dict(me=node.id, port=node.port, peers=peers, messages=msgs)

    def tick(self, dt):
        self.state = self.build_state()
        if self.sm.current == "companions":
            self.companions_screen.update_ui(self.state)
        elif self.sm.current == "chat":
            self.chat_screen.update_ui(self.state)

    def on_stop(self):
        self.node.running = False


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="ECHO Mobile Kivy Peer")
    parser.add_argument("--id", default="A", help="Peer ID")
    parser.add_argument("--port", default=5001, type=int, help="Port")
    parser.add_argument("--config", default="peers.json", help="Path to peers.json")
    args, _ = parser.parse_known_args()

    neighbours = peer.load_peer_table(args.config, args.id) if hasattr(peer, 'load_peer_table') else {}

    node = GuiNode(args.id, args.port, neighbours)
    peer.handle_connection = gui_handle_connection

    server = peer.start_listener(args.port, node)
    node.start_background()

    app = EchoApp(node)
    try:
        app.run()
    finally:
        node.running = False
        if server:
            try: server.close()
            except Exception: pass


if __name__ == '__main__':
    main()