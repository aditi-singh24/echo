"""
peer.py (Module 1: Core Messaging)
Serverless LAN chat. Each peer is a tiny post office:
  - a mailbox      (listening socket, background thread)
  - a carrier      (sending socket, opened per message)
  - an address book (peer table from peers.json)

Run:
    python peer.py --id A --port 5001 --config peers.json

Module 1 is DIRECT messaging only. No routing, forwarding, ACKs or
heartbeats yet. The "type", "hops" and "ttl" fields are already in the
message format so Modules 2 and 3 can plug in without changing it.

peer.py (Module 2: Routing and Forwarding)
Serverless LAN chat. Each peer is a tiny post office with a road map:
  - a mailbox      (listening socket, background thread)
  - a carrier      (sending socket, opened per message)
  - an address book (direct neighbours from peers.json)
  - a road map     (routing table, learned with Distance Vector)
  - a night watch  (heartbeats that detect dead neighbours)

Message types (same JSON format as Module 1):
  chat       a user message, may be forwarded across several peers
  heartbeat  "I am alive", sent to direct neighbours only
  dv         a distance vector (my routing table), direct neighbours only

"hops" counts how many times a chat message was RELAYED.
A direct message has hops 0. A message A -> B -> C arrives with hops 1.

peer.py (Module 3: Reliability)
Adds registered post (ACKs, retries and delivery status).

  ack        "I received message <id>", travels back to the sender

Encryption (added)
  Chat text is locked in a box before it leaves the sender and unlocked
  only at the final receiver. Relays pass the locked box along.
  Built with the Python standard library only (no pip install needed).
  Every peer must use the same SHARED_SECRET below.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import socket
import sys
import threading
import time
import uuid
import zlib

# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

DEFAULT_TTL = 5
REQUIRED_FIELDS = ("id", "type", "src", "dst", "payload", "hops", "ttl", "crc")
CONNECT_TIMEOUT = 3      # seconds, chat messages
HEARTBEAT_TIMEOUT = 1    # seconds, heartbeats and routing updates
HEARTBEAT_INTERVAL = 2   # send a heartbeat every 2 s
DEAD_AFTER = 6           # neighbour is dead after 6 s of silence
DV_INTERVAL = 5          # periodic routing update every 5 s
INFINITY = 16            # cost meaning "unreachable" (used for poison reverse)
ACK_TIMEOUT = 3          # wait this long for an ack before retrying
MAX_RETRIES = 3          # retries after the first send, then mark FAILED

# The group password. Every peer must have the SAME value.
# Change it to your own phrase. Note: this repo is public, so anyone who
# reads this file can read your messages. Fine for a course demo.
SHARED_SECRET = "xxxx-change-this-group-password-xxxx"

# ---------------------------------------------------------------------------
# ENCRYPTION: the locked box (standard library only)
# ---------------------------------------------------------------------------
# Turn the password into two separate keys: one to scramble, one to sign.
_MASTER = hashlib.pbkdf2_hmac("sha256", SHARED_SECRET.encode("utf-8"),
                              b"echo-lan-chat-v1", 100000, 64)
_ENC_KEY = _MASTER[:32]
_MAC_KEY = _MASTER[32:]


def _keystream(nonce, length):
    """Endless scrambling bytes made from the key and a one time nonce."""
    out = b""
    counter = 0
    while len(out) < length:
        block = hmac.new(_ENC_KEY, nonce + counter.to_bytes(8, "big"),
                         hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def encrypt_text(text):
    """
    Plain text -> one safe-to-send string.
    Layout: [16 byte nonce][scrambled text][32 byte signature], base64 encoded.
    A fresh random nonce means the same text never looks the same twice.
    """
    data = text.encode("utf-8")
    nonce = os.urandom(16)
    scrambled = bytes(a ^ b for a, b in zip(data, _keystream(nonce, len(data))))
    tag = hmac.new(_MAC_KEY, nonce + scrambled, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + scrambled + tag).decode("ascii")


def decrypt_text(token):
    """
    Safe-to-send string -> plain text.
    Returns None if the signature is wrong (wrong password or tampered).
    """
    try:
        raw = base64.urlsafe_b64decode(str(token).encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None
    if len(raw) < 48:
        return None
    nonce, scrambled, tag = raw[:16], raw[16:-32], raw[-32:]
    expected = hmac.new(_MAC_KEY, nonce + scrambled, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        return None
    data = bytes(a ^ b for a, b in zip(scrambled, _keystream(nonce, len(scrambled))))
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# STARTUP: arguments and neighbour table
# ---------------------------------------------------------------------------

def parse_args():
    """Read --id, --port and --config from the command line."""
    parser = argparse.ArgumentParser(description="Serverless LAN chat peer")
    parser.add_argument("--id", required=True, help="this peer's ID, e.g. A")
    parser.add_argument("--port", required=True, type=int,
                        help="port this peer listens on, e.g. 5001")
    parser.add_argument("--config", required=True,
                        help="path to peers.json")
    return parser.parse_args()


def load_peer_table(config_path, my_id):
    """
    Open the shared peers.json and keep only MY section (my direct neighbours).
    Returns {peer_id: {"id", "ip", "port", "status"}}.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    if my_id not in config:
        print(f"Error: '{my_id}' has no section in {config_path}")
        sys.exit(1)
    table = {}
    for entry in config[my_id]:
        table[entry["id"]] = entry
    return table


# ---------------------------------------------------------------------------
# MESSAGE FUNCTIONS: build, serialize, parse, CRC
# ---------------------------------------------------------------------------

def compute_crc(msg):
    """
    CRC32 over every field except "crc", "hops" and "ttl".

    hops and ttl change at every relay, so leaving them out makes the CRC
    an end to end check: whatever the sender wrote is exactly what the
    final receiver verifies, and relays do not need to recompute it.

    JSON uses sort_keys and compact separators so both sides produce the
    exact same text for the same fields.
    """
    body = {k: v for k, v in msg.items() if k not in ("crc", "hops", "ttl")}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


def build_message(src, dst, payload, msg_type="chat", ttl=DEFAULT_TTL):
    msg = {
        "id": str(uuid.uuid4()),
        "type": msg_type,
        "src": src,
        "dst": dst,
        "payload": payload,
        "hops": 0,
        "ttl": ttl,
    }
    msg["crc"] = compute_crc(msg)
    return msg


def serialize(msg):
    """Dict to one line of JSON ending with a newline (the message boundary)."""
    return json.dumps(msg) + "\n"


def parse(line):
    """
    One line of text back to a dict.
    Returns None if the line is not valid JSON or is missing a field.
    """
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict):
        return None
    for field in REQUIRED_FIELDS:
        if field not in msg:
            return None
    return msg


def verify_crc(msg):
    return compute_crc(msg) == msg["crc"]


# ---------------------------------------------------------------------------
# SEND PATH: the carrier
# ---------------------------------------------------------------------------

def send_to_peer(peer, data, timeout=CONNECT_TIMEOUT):
    """Open a connection to one direct neighbour and send one line."""
    try:
        with socket.create_connection((peer["ip"], peer["port"]),
                                      timeout=timeout) as sock:
            sock.sendall(data.encode("utf-8"))
        return True, ""
    except OSError as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# THE NODE: routing table, heartbeats, forwarding
# ---------------------------------------------------------------------------

class Node:
    """
    Everything one peer knows and does.

    routes: {dest: {"next": neighbour_id, "cost": hops}}
            cost INFINITY means "no longer reachable".
    """

    def __init__(self, my_id, port, neighbours):
        self.id = my_id
        self.port = port
        self.neighbours = neighbours
        self.prompt = f"{my_id}> "
        self.lock = threading.RLock()       # guards routes and neighbours
        self.out_lock = threading.Lock()    # keeps console output tidy
        self.trigger = threading.Event()    # "send a routing update now"
        self.running = True
        self.debug = False
        self.pending = {}    # msg id -> entry for every chat I sent
        self.outbox = []     # msg ids in the order I sent them
        self.seen = set()    # ids of chats already delivered to me
        now = time.time()
        self.routes = {my_id: {"next": my_id, "cost": 0}}
        for nid, n in self.neighbours.items():
            n["last_seen"] = now
            if n["status"] == "up":
                self.routes[nid] = {"next": nid, "cost": 1}

    # ----- console output -------------------------------------------------

    def say(self, text):
        """Print an event line from any thread, then redraw the prompt."""
        with self.out_lock:
            print(f"\n{text}")
            print(self.prompt, end="", flush=True)

    # ----- background workers --------------------------------------------

    def start_background(self):
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        threading.Thread(target=self.dv_loop, daemon=True).start()
        threading.Thread(target=self.retry_loop, daemon=True).start()
        self.trigger.set()   # first routing update goes out right away

    def send_async(self, peer, data, timeout):
        """Fire and forget, so one slow or dead neighbour never blocks us."""
        threading.Thread(target=send_to_peer, args=(peer, data, timeout),
                         daemon=True).start()

    def heartbeat_loop(self):
        """Every HEARTBEAT_INTERVAL: ping all neighbours, then check silence."""
        while self.running:
            for nid, n in list(self.neighbours.items()):
                hb = build_message(self.id, nid, "", "heartbeat", ttl=1)
                self.send_async(n, serialize(hb), HEARTBEAT_TIMEOUT)
            self.check_neighbours()
            time.sleep(HEARTBEAT_INTERVAL)

    def dv_loop(self):
        """Send a routing update every DV_INTERVAL, or sooner if triggered."""
        while self.running:
            self.trigger.wait(timeout=DV_INTERVAL)
            self.trigger.clear()
            time.sleep(0.2)   # lets a burst of changes become one update
            self.send_dv_to_all()

    # ----- neighbour liveness --------------------------------------------

    def mark_alive(self, nid):
        """A heartbeat or update arrived from neighbour nid."""
        came_back = False
        with self.lock:
            n = self.neighbours.get(nid)
            if n is None:
                return
            n["last_seen"] = time.time()
            if n["status"] != "up":
                n["status"] = "up"
                self.routes[nid] = {"next": nid, "cost": 1}
                came_back = True
        if came_back:
            self.say(f"[LINK UP] {nid} is back")
            self.trigger.set()

    def check_neighbours(self):
        """Declare neighbours dead after DEAD_AFTER seconds of silence."""
        now = time.time()
        dead = []
        with self.lock:
            for nid, n in self.neighbours.items():
                if n["status"] == "up" and now - n["last_seen"] > DEAD_AFTER:
                    n["status"] = "down"
                    dead.append(nid)
                    for r in self.routes.values():
                        if r["next"] == nid:
                            r["cost"] = INFINITY
        for nid in dead:
            self.say(f"[LINK DOWN] no heartbeat from {nid} for {DEAD_AFTER}s, "
                     f"routes via {nid} marked unreachable")
        if dead:
            self.trigger.set()

    # ----- Distance Vector ------------------------------------------------

    def vector_for(self, nid):
        """
        My routing table as {dest: cost}, tailored for neighbour nid.

        Poison reverse: a route I learned THROUGH nid is advertised back to
        nid with cost INFINITY, so nid never believes I can reach it via nid.
        """
        with self.lock:
            vec = {}
            for dst, r in self.routes.items():
                vec[dst] = INFINITY if r["next"] == nid else r["cost"]
            return vec

    def send_dv_to_all(self):
        with self.lock:
            targets = [(nid, n) for nid, n in self.neighbours.items()
                       if n["status"] == "up"]
        for nid, n in targets:
            dv = build_message(self.id, nid, self.vector_for(nid), "dv", ttl=1)
            self.send_async(n, serialize(dv), HEARTBEAT_TIMEOUT)

    def process_dv(self, nid, vector):
        """
        Bellman-Ford step: for each destination, my cost via nid is
        (nid's cost) + 1. Adopt it if it is new, better, or if nid is already
        my next hop for that destination (then its word is final, good or bad).
        """
        notes = []
        with self.lock:
            for dst, raw in vector.items():
                if dst == self.id:
                    continue
                try:
                    new_cost = min(int(raw) + 1, INFINITY)
                except (TypeError, ValueError):
                    continue
                cur = self.routes.get(dst)
                if cur is None:
                    if new_cost < INFINITY:
                        self.routes[dst] = {"next": nid, "cost": new_cost}
                        notes.append(f"[ROUTE] {dst} reachable via {nid}, "
                                     f"cost {new_cost}")
                elif cur["next"] == nid:
                    if cur["cost"] != new_cost:
                        cur["cost"] = new_cost
                        if new_cost >= INFINITY:
                            notes.append(f"[ROUTE] {dst} unreachable "
                                         f"(via {nid} reports no path)")
                        else:
                            notes.append(f"[ROUTE] {dst} via {nid}, "
                                         f"cost {new_cost}")
                elif new_cost < cur["cost"]:
                    self.routes[dst] = {"next": nid, "cost": new_cost}
                    notes.append(f"[ROUTE] {dst} now via {nid}, "
                                 f"cost {new_cost}")
        if notes:
            self.say("\n".join(notes))
            self.trigger.set()   # table changed, tell the neighbours now

    def next_hop(self, dst):
        """Neighbour to hand a message for dst to, or None if no route."""
        with self.lock:
            r = self.routes.get(dst)
            if r is None or r["cost"] >= INFINITY or r["next"] == self.id:
                return None
            return r["next"]

    # ----- reliability: send, retry, acknowledge --------------------------

    def send_chat(self, dst, text):
        """
        Send a new chat and start tracking it.
        The text is locked in a box (encrypted) before it is put in the message.
        Returns None if there is no route, else (msg, hop, ok, reason).
        """
        hop = self.next_hop(dst)
        if hop is None:
            return None
        msg = build_message(self.id, dst, encrypt_text(text))
        entry = {"msg": msg, "dst": dst, "text": text, "status": "SENT",
                 "retries": 0, "deadline": time.time() + ACK_TIMEOUT}
        with self.lock:
            self.pending[msg["id"]] = entry
            self.outbox.append(msg["id"])
        ok, reason = send_to_peer(self.neighbours[hop], serialize(msg))
        return msg, hop, ok, reason

    def retry_loop(self):
        """Twice a second, look for chats whose ack deadline has passed."""
        while self.running:
            time.sleep(0.5)
            now = time.time()
            with self.lock:
                due = [self.pending[mid] for mid in self.outbox
                       if self.pending[mid]["status"] == "SENT"
                       and now >= self.pending[mid]["deadline"]]
            for entry in due:
                self.retry_or_fail(entry)

    def retry_or_fail(self, entry):
        short = entry["msg"]["id"][:8]
        dst = entry["dst"]
        with self.lock:
            if entry["status"] != "SENT":
                return
            if entry["retries"] >= MAX_RETRIES:
                entry["status"] = "FAILED"
                failed = True
            else:
                entry["retries"] += 1
                entry["deadline"] = time.time() + ACK_TIMEOUT
                failed = False
            n = entry["retries"]
        if failed:
            self.say(f"[FAILED] {short} to {dst}: no ack after "
                     f"{MAX_RETRIES} retries")
            return
        hop = self.next_hop(dst)   # fresh look at the routing table
        if hop is None:
            self.say(f"[RETRY {n}/{MAX_RETRIES}] {short} to {dst}: "
                     f"no route right now, will look again")
            return
        msg = dict(entry["msg"])
        msg["hops"] = 0
        msg["ttl"] = DEFAULT_TTL
        ok, reason = send_to_peer(self.neighbours[hop], serialize(msg))
        extra = "" if ok else f" (could not reach {hop}: {reason})"
        self.say(f"[RETRY {n}/{MAX_RETRIES}] {short} to {dst} via {hop}{extra}")

    def send_ack(self, msg):
        """Tell the original sender that message msg arrived."""
        ack = build_message(self.id, msg["src"], msg["id"], "ack")
        hop = self.next_hop(msg["src"])
        if hop is None:
            self.say(f"[ACK NOT SENT] no route back to {msg['src']}")
            return
        self.send_async(self.neighbours[hop], serialize(ack), CONNECT_TIMEOUT)

    def handle_ack(self, msg):
        if msg["dst"] != self.id:
            self.relay(msg)
            return
        mid = msg["payload"]
        with self.lock:
            entry = self.pending.get(mid)
            if entry is None or entry["status"] == "DELIVERED":
                return
            entry["status"] = "DELIVERED"
        self.say(f"[DELIVERED] {str(mid)[:8]} to {entry['dst']} "
                 f"(ack from {msg['src']})")

    # ----- receiving ------------------------------------------------------

    def handle_message(self, msg):
        kind = msg["type"]
        if kind in ("heartbeat", "dv"):
            src = msg["src"]
            if src not in self.neighbours:
                return
            self.mark_alive(src)
            if kind == "dv" and isinstance(msg["payload"], dict):
                self.process_dv(src, msg["payload"])
            if self.debug:
                self.say(f"[debug] {kind} from {src}")
            return
        if kind == "chat":
            self.handle_chat(msg)
        elif kind == "ack":
            self.handle_ack(msg)

    def handle_chat(self, msg):
        if msg["dst"] == self.id:
            self.deliver(msg)
        else:
            self.relay(msg)

    def deliver(self, msg):
        """
        A chat addressed to me: unlock it, show it once, acknowledge it every time.
        If it cannot be unlocked (wrong password or tampered), drop it and send no ack.
        """
        with self.lock:
            duplicate = msg["id"] in self.seen
        if duplicate:
            self.say(f"[DUPLICATE] {msg['id'][:8]} from {msg['src']} "
                     f"ignored, sending the ack again")
            self.send_ack(msg)
            return
        text = decrypt_text(msg["payload"])
        if text is None:
            self.say(f"[DECRYPT FAIL] message from {msg['src']} dropped "
                     f"(wrong password or tampered)")
            return
        with self.lock:
            self.seen.add(msg["id"])
        self.say(f"[CRC PASS] from {msg['src']}: {text} "
                 f"(hops {msg['hops']}, encrypted)")
        self.send_ack(msg)

    def relay(self, msg):
        """Not for me: pass a chat or an ack one step closer to its target."""
        short = (msg["payload"] if msg["type"] == "ack" else msg["id"])[:8]
        label = msg["type"]
        msg["hops"] += 1
        msg["ttl"] -= 1
        if msg["ttl"] <= 0:
            self.say(f"[TTL EXPIRED] dropped {label} {short} "
                     f"({msg['src']} -> {msg['dst']})")
            return
        hop = self.next_hop(msg["dst"])
        if hop is None:
            self.say(f"[NO ROUTE] dropped {label} {short} ({msg['src']} -> "
                     f"{msg['dst']}), I have no route to {msg['dst']}")
            return
        ok, reason = send_to_peer(self.neighbours[hop], serialize(msg))
        if ok:
            self.say(f"[FORWARD] {label} {short} {msg['src']} -> "
                     f"{msg['dst']} via {hop} "
                     f"(hops {msg['hops']}, ttl {msg['ttl']})")
        else:
            self.say(f"[FORWARD FAILED] {label} {short} to {hop}: {reason}")


# ---------------------------------------------------------------------------
# RECEIVE PATH: the mailbox
# ---------------------------------------------------------------------------

def handle_connection(conn, node):
    """
    Read one connection line by line. Each line is one message.
    Bad JSON is reported. A CRC mismatch is dropped (never treated as valid).
    """
    with conn:
        try:
            reader = conn.makefile("r", encoding="utf-8")
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                msg = parse(line)
                if msg is None:
                    node.say("[DROPPED] unreadable message "
                             "(bad JSON or missing field)")
                    continue
                if not verify_crc(msg):
                    node.say(f"[CRC FAIL] message from {msg['src']} dropped")
                    continue
                node.handle_message(msg)
        except (OSError, UnicodeDecodeError):
            return


def listener_loop(server, node):
    """Wait at the mailbox forever. Each connection gets its own thread."""
    while True:
        try:
            conn, _addr = server.accept()
        except OSError:
            break   # server socket closed, stop listening
        threading.Thread(target=handle_connection, args=(conn, node),
                         daemon=True).start()


def start_listener(port, node):
    """Open the mailbox on the given port and run it in a background thread."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen()
    threading.Thread(target=listener_loop, args=(server, node),
                     daemon=True).start()
    return server


# ---------------------------------------------------------------------------
# CHAT UI: the counter
# ---------------------------------------------------------------------------

def print_help(node):
    print(f"\nPeer {node.id} is running.")
    print(f"Direct neighbours: {', '.join(node.neighbours) or '(none)'}")
    print("Send a message: <peer_id> <text>   e.g.  C hello there")
    print("Commands: /routes /peers /status /debug /help /quit\n")


def print_peers(node):
    now = time.time()
    with node.lock:
        for nid, n in node.neighbours.items():
            age = now - n["last_seen"]
            print(f"  {nid}  {n['ip']}:{n['port']}  status={n['status']}  "
                  f"last heard {age:.0f}s ago")


def print_routes(node):
    with node.lock:
        rows = sorted((d, dict(r)) for d, r in node.routes.items()
                      if d != node.id)
    if not rows:
        print("  (no routes)")
        return
    print("  dest  next  cost")
    for dst, r in rows:
        if r["cost"] >= INFINITY:
            print(f"  {dst:<5} {'-':<5} unreachable")
        else:
            print(f"  {dst:<5} {r['next']:<5} {r['cost']}")


def print_status(node):
    with node.lock:
        rows = [(mid, dict(node.pending[mid])) for mid in node.outbox]
    if not rows:
        print("  (no messages sent yet)")
        return
    print("  id        to    status     retries  text")
    for mid, e in rows:
        print(f"  {mid[:8]}  {e['dst']:<4}  {e['status']:<10} "
              f"{e['retries']:<8} {e['text']}")


def run_chat_ui(node):
    """Read what the user types, build the message, hand it to the carrier."""
    print_help(node)
    while True:
        try:
            line = input(node.prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return
        if not line:
            continue
        if line == "/quit":
            print("Bye.")
            return
        if line == "/help":
            print_help(node)
            continue
        if line == "/peers":
            print_peers(node)
            continue
        if line == "/routes":
            print_routes(node)
            continue
        if line == "/status":
            print_status(node)
            continue
        if line == "/debug":
            node.debug = not node.debug
            print(f"  debug {'on' if node.debug else 'off'} "
                  f"(shows every heartbeat and routing update)")
            continue
        parts = line.split(" ", 1)
        if len(parts) < 2 or not parts[1].strip():
            print("Usage: <peer_id> <text>")
            continue
        dst, text = parts[0], parts[1].strip()
        if dst == node.id:
            print("  that is me. Pick another peer.")
            continue
        result = node.send_chat(dst, text)
        if result is None:
            print(f"  no route to {dst}. Try /routes")
            continue
        msg, hop, ok, reason = result
        via = "" if hop == dst else f" via {hop}"
        if ok:
            print(f"  sent to {dst}{via} (id {msg['id'][:8]}), waiting for ack")
        else:
            print(f"  could not reach {hop}: {reason}. Will retry.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    neighbours = load_peer_table(args.config, args.id)
    node = Node(args.id, args.port, neighbours)
    server = start_listener(args.port, node)
    node.start_background()
    try:
        run_chat_ui(node)
    finally:
        node.running = False
        server.close()


if __name__ == "__main__":
    main()
