"""Super Stream Bros Ultimate dock: bracket + recording timestamps for the Ultimate side.

Settings: dock_config.json (written on first start). Set "shortLink" to your series' start.gg
short link (start.gg/<name>, which redirects to the newest tournament), or load a slug in the gear menu.

Run:   start_dock.bat   (or: python dock_server.py)
Then in OBS: Docks > Custom Browser Docks, URL http://127.0.0.1:8766/

- Same start.gg controls as the Melee Stream Dock (call / start / report / DQ / reset),
  but for the tournament's Ultimate event. No overlay files: the Ultimate side only records.
- Two recordings (Recording 1 = main OBS, Recording 2 = portable OBS; called "stream" in the
  code, and on the page if slotLabel is set to "Stream"). "Put on recording 1/2" saves
  a timestamp so the recordings can be cut into per-set videos later. Timestamps go to
  timestamps\\<tournament>\\ (log.jsonl + timestamps.csv + one chapter list per stream).
- Setups (named in the gear menu): "Put on setup" time-stamps sets on every setup, recorded or
  not, for data on all sets (setups.jsonl / setups.csv / Setup times.txt). Stream 1/2 each
  record one setup; putting a set on that setup is the same as "Put on stream N".
- Characters: picked per player when reporting (or "Characters..." on a finished set), from
  start.gg's Ultimate cast (characters.json). Saved per tournament (characters.json in the
  timestamps folder, used in the chapter lists for video titles) and per player
  (player_characters.json, which pre-fills each player's usual characters).
- start.gg token comes from the STARTGG_TOKEN environment variable. It stays in this
  process; it is never sent to the page or written to disk.
- Listens on 127.0.0.1 only. Python standard library only.
"""

import collections
import csv
import io
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import lan as lanmod  # optional LAN access (lan.py next to this file)

# Try IPv4 before IPv6. Some networks have a start.gg IPv6 address that doesn't answer, and
# Python waits out the full timeout per address before falling back (docks stall 20-40 s).
_getaddrinfo = socket.getaddrinfo


def _ipv4_first(*args, **kwargs):
    return sorted(_getaddrinfo(*args, **kwargs), key=lambda r: r[0] != socket.AF_INET)


socket.getaddrinfo = _ipv4_first

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
CONFIG_FILE = os.path.join(HERE, "dock_config.json")
STATE_FILE = os.path.join(HERE, "dock_state.json")
LOG_ROOT = os.path.join(HERE, "timestamps")
CAST_FILE = os.path.join(HERE, "characters.json")            # start.gg's Ultimate cast (shipped)
PLAYERS_FILE = os.path.join(HERE, "player_characters.json")  # player id -> characters per set (shipped, grows)

HOST, PORT = "127.0.0.1", 8766  # the Melee Stream Dock uses 8765, so both can run on one PC
API_URL = "https://api.start.gg/gql/alpha"
ULTIMATE_ID = 1386  # start.gg videogame id for Super Smash Bros. Ultimate
UA = "SuperStreamBrosUltimateDock/1.0"
STREAMS = ("1", "2")  # 1 = main OBS (hosts this dock), 2 = portable OBS
SETUPS_MAX = 16
CHARS_MAX = 3  # characters per player per set (the page allows the same)

DEFAULT_CONFIG = {
    # Your series' start.gg short link (redirects to its newest tournament), e.g.
    # "https://www.start.gg/YourSeries". Empty: load a slug in the gear menu instead.
    "shortLink": "",
    "tournamentSlug": "",  # filled in automatically
    "pinSlug": False,      # True = stay on tournamentSlug ("Load slug"); False = follow shortLink each start
    "eventId": None,
    "streamIds": {"1": None, "2": None},  # optional start.gg stream per recording (assigned on "Put on stream")
    "pollSeconds": 20,
    # What the two OBS outputs are called on the page and in the files ("Recording 1"). Set to
    # "Stream" if the Ultimate side starts streaming; internal keys stay "stream" either way.
    "slotLabel": "Recording",
    # Setup names in order (count = len), kept week to week; set in the gear menu.
    "setups": ["Setup 1", "Setup 2", "Setup 3", "Setup 4"],
    "streamSetups": {"1": 0, "2": 1},  # which setup (index) each recording captures; None = none
    # Big events / LAN (see guides\06 in the Super Stream Bros package): read at start, restart after changing.
    "port": 8766,                  # the env var SSB_ULTIMATE_DOCK_PORT wins if set
    "tokenVar": "STARTGG_TOKEN",   # user env var holding this instance's start.gg token
    "lan": False,                  # True = other devices on the network may use the pages (needs lanPin)
    "lanPin": "",                  # full control from other devices (6+ characters)
    "lanViewPin": "",              # optional: look-only access (bracket screens)
    "bracketCacheSeconds": 5,      # whole-bracket fetches are shared for this long (raise for big brackets)
    "maxBracketPages": 20,         # 25 sets per page: 20 = up to 500 sets
}

LOCK = threading.RLock()
CACHE_LOCK = threading.Lock()    # guards the per-key fetch locks in Dock.cached
PENDING_LOCK = threading.Lock()  # actions queued while start.gg sets up the bracket


# ---------------------------------------------------------------- files

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def save_json(path, data):
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))


# Settings needed before the dock starts (dock_config.json; defaults = this PC only, as before).
BOOT_CONFIG = load_json(CONFIG_FILE, {})
PORT = int(os.environ.get("SSB_ULTIMATE_DOCK_PORT") or BOOT_CONFIG.get("port") or PORT)
TOKEN_VAR = str(BOOT_CONFIG.get("tokenVar") or "STARTGG_TOKEN").strip()
LAN = lanmod.Lan(BOOT_CONFIG, PORT, "Super Stream Bros Ultimate")
HOST = LAN.host
PRIVATE_KEYS = ("lanPin", "lanViewPin")  # never sent to the pages


def public_config(cfg):
    return {k: v for k, v in cfg.items() if k not in PRIVATE_KEYS}


def clock(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


def day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def video_time(seconds):
    s = max(0, int(seconds))
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)


# ---------------------------------------------------------------- token / start.gg

def get_token():
    tok = os.environ.get(TOKEN_VAR, "").strip()  # "tokenVar" in dock_config.json, default STARTGG_TOKEN
    if tok:
        return tok
    # Fallback: a user env var set (set_token.bat) after this window was opened.
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return str(winreg.QueryValueEx(k, TOKEN_VAR)[0]).strip()
        except OSError:
            pass
    return ""


class ApiError(Exception):
    pass


class RateLimited(ApiError):
    """start.gg said "too many requests" (or the dock's own budget is used up). Reads fall back
    to the last data the dock has; see Dock.cached."""


# start.gg allows 80 requests per 60 s per token. The dock keeps its own reads under READ_BUDGET
# so there is always room for actions (report, start, call...), which are never held back.
RATE_WINDOW, READ_BUDGET = 60.0, 55
RATE_LOCK = threading.Lock()
RATE_CALLS = collections.deque()   # times of the requests sent in the last minute
RATE_PAUSE = [0.0]                 # no reads before this time (set when start.gg answers 429)


def rate_gate(is_read):
    now = time.time()
    with RATE_LOCK:
        while RATE_CALLS and now - RATE_CALLS[0] > RATE_WINDOW:
            RATE_CALLS.popleft()
        if is_read and (now < RATE_PAUSE[0] or len(RATE_CALLS) >= READ_BUDGET):
            raise RateLimited("start.gg rate limit: showing the last list, catching up in a few seconds.")
        RATE_CALLS.append(now)


NET_HELP = "No internet connection to start.gg (check Wi-Fi). Timestamps still work."


def open_with_retry(req, opener=None, tries=3):
    for attempt in range(tries):
        try:
            with (opener.open(req, timeout=20) if opener else urllib.request.urlopen(req, timeout=20)) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise ApiError(f"{NET_HELP} ({getattr(e, 'reason', e)})") from None
            time.sleep(1.5 * (attempt + 1))


def gql(query, variables=None):
    token = get_token()
    if not token:
        raise ApiError("STARTGG_TOKEN is not set. Run set_token.bat, then restart start_dock.bat.")
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": UA,
    })
    is_read = not query.lstrip().startswith("mutation")
    for attempt in range(4):
        rate_gate(is_read)
        try:
            data = json.loads(open_with_retry(req).decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read(500).decode("utf-8", "replace")
            if e.code != 429:
                raise ApiError(f"start.gg HTTP {e.code}: {detail}") from None
            # Too many requests: hold the reads back for a while. An action waits and tries again.
            with RATE_LOCK:
                RATE_PAUSE[0] = max(RATE_PAUSE[0], time.time() + 15)
            if is_read or attempt == 3:
                raise RateLimited("start.gg rate limit reached. Wait a few seconds and try again."
                                  if not is_read else "start.gg rate limit: showing the last list, catching up in a few seconds.") from None
            time.sleep(4 * (attempt + 1))
    if data.get("errors"):
        raise ApiError("start.gg: " + "; ".join(str(x.get("message")) for x in data["errors"]))
    return data.get("data") or {}


def resolve_short_link(url):
    """Follow start.gg/<shortlink> to /tournament/<slug>/... without following redirects."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    loc = ""
    try:
        open_with_retry(req, opener)
    except urllib.error.HTTPError as e:  # the redirect arrives as a 3xx "error"
        loc = e.headers.get("Location", "")
    m = re.search(r"/tournament/([a-z0-9-]+)", loc or "")
    if not m:
        raise ApiError(f"Could not resolve {url} to a tournament (got {loc!r}).")
    return m.group(1)


Q_TOURNAMENT = """
query T($slug: String!) {
  tournament(slug: $slug) {
    id name slug startAt state
    events { id name slug numEntrants state videogame { id } }
    streams { id streamName streamSource }
  }
}"""

SET_FIELDS = """
  id identifier fullRoundText round state winnerId startedAt completedAt
  stream { id streamName }
  station { id number }
  phaseGroup { id bracketType }
  slots {
    entrant { id name initialSeedNum participants { id gamerTag prefix player { id } } }
    seed { seedNum entrant { id } }
    standing { stats { score { value } } }
  }
"""

Q_SETS = """
query S($eventId: ID!, $states: [Int], $sort: SetSortType, $perPage: Int!) {
  event(id: $eventId) {
    id name
    sets(page: 1, perPage: $perPage, sortType: $sort, filters: { state: $states, hideEmpty: true }) {
      nodes {""" + SET_FIELDS + """}
    }
  }
}"""

# start.gg refuses a request that returns more than 1000 objects ("query complexity"). Measured
# on PROTOCOL #58 Ultimate (see PROJECT_NOTES); re-measure (extensions.queryComplexity) after adding fields.
# A set costs about 30 objects here: bracket 25 per page = 751, open list 30 = 871 (40 was refused).
PAGE_BRACKET, PAGE_OPEN = 25, 30

# Whole bracket (every state, empty future sets too) for the bracket overview page.
Q_BRACKET = """
query B($eventId: ID!, $page: Int!) {
  event(id: $eventId) {
    sets(page: $page, perPage: """ + str(PAGE_BRACKET) + """, sortType: ROUND, filters: { hideEmpty: false }) {
      pageInfo { totalPages }
      nodes {
        id identifier fullRoundText round state winnerId startedAt completedAt
        stream { id streamName }
        station { id number }
        phaseGroup { id displayIdentifier bracketType phase { id name phaseOrder } }
        slots {
          prereqType prereqId prereqPlacement
          entrant { id name initialSeedNum participants { id gamerTag prefix player { id } } }
          seed { seedNum entrant { id } }
          standing { stats { score { value } } }
        }
      }
    }
  }
}"""

MUTATIONS = {
    "call": "mutation M($setId: ID!) { markSetCalled(setId: $setId) { id state } }",
    "start": "mutation M($setId: ID!) { markSetInProgress(setId: $setId) { id state } }",
    "stream": "mutation M($setId: ID!, $streamId: ID!) { assignStream(setId: $setId, streamId: $streamId) { id stream { id } } }",
    "report": ("mutation M($setId: ID!, $winnerId: ID, $isDQ: Boolean, $gameData: [BracketSetGameDataInput]) "
               "{ reportBracketSet(setId: $setId, winnerId: $winnerId, isDQ: $isDQ, gameData: $gameData) { id state } }"),
    "reset": "mutation M($setId: ID!) { resetSet(setId: $setId, resetDependentSets: false) { id state } }",
}


def tag_of(slot):
    return (f"{slot['prefix']} | {slot['tag']}" if slot.get("prefix") else slot.get("tag")) or "?"


def simplify_set(s):
    slots = []
    for sl in s.get("slots") or []:
        ent = sl.get("entrant") or {}
        parts = ent.get("participants") or []
        p = parts[0] if parts else {}
        score = (((sl.get("standing") or {}).get("stats") or {}).get("score") or {}).get("value")
        slots.append({
            "entrantId": ent.get("id"),
            "playerId": (p.get("player") or {}).get("id"),  # same every week (entrant ids aren't)
            "tag": p.get("gamerTag") or ent.get("name") or "",
            "prefix": p.get("prefix") or "",
            "score": score,
            # initialSeedNum is often empty; the phase seed is on the slot (first-round sets only,
            # Dock.fill_seeds copies it to the player's later sets).
            "seed": ent.get("initialSeedNum") or (
                (sl.get("seed") or {}).get("seedNum")
                if str(((sl.get("seed") or {}).get("entrant") or {}).get("id")) == str(ent.get("id")) else None),

            "prereqType": sl.get("prereqType"),
            "prereqId": sl.get("prereqId"),
            "prereqPlacement": sl.get("prereqPlacement"),
        })
    pg = s.get("phaseGroup") or {}
    return {
        "group": pg.get("displayIdentifier"),
        "groupId": pg.get("id"),
        "bracketType": pg.get("bracketType"),
        "phase": (pg.get("phase") or {}).get("name"),
        "phaseOrder": (pg.get("phase") or {}).get("phaseOrder"),
        "id": s.get("id"),
        "identifier": s.get("identifier"),
        "round": s.get("fullRoundText") or "",
        "roundNum": s.get("round"),
        "state": s.get("state"),
        "winnerId": s.get("winnerId"),
        "stream": (s.get("stream") or {}).get("streamName"),
        "streamId": (s.get("stream") or {}).get("id"),
        "station": (s.get("station") or {}).get("number"),
        "startedAt": s.get("startedAt"),
        "completedAt": s.get("completedAt"),
        "slots": slots,
    }


def result_text(s):
    """'A 3-1 B' (winner first) or 'DQ: B' for a finished set."""
    sl = s.get("slots") or []
    if len(sl) != 2:
        return ""
    loser = next((x for x in sl if x.get("score") == -1), None)
    if loser:
        return f"DQ: {tag_of(loser)}"
    a, b = sl
    if str(b.get("entrantId")) == str(s.get("winnerId")):
        a, b = b, a
    return f"{tag_of(a)} {a.get('score') or 0}-{b.get('score') or 0} {tag_of(b)}"


# ---------------------------------------------------------------- timestamp log

EVENT_LABEL = {"rec_start": "Recording started", "on_stream": "On stream", "set_end": "Set over", "mark": "Mark"}


def with_chars(name, chars):
    """'Swizzy (Terry, Random)': the form used in video titles."""
    short = ["Random" if c == "Random Character" else c for c in chars or []]
    return f"{name} ({', '.join(short)})" if short else name


def describe(ev, chars=None):
    """One readable line for an event (chapter lists, CSV, dock log). chars = (p1 chars, p2 chars)."""
    kind = ev.get("event")
    c1, c2 = chars or ([], [])
    vs = f"{with_chars(ev.get('p1') or '?', c1)} vs {with_chars(ev.get('p2') or '?', c2)}" if ev.get("setId") else ""
    if kind == "on_stream":
        ident = f" (set {ev['identifier']})" if ev.get("identifier") else ""
        return f"{ev.get('round') or 'Set'}: {vs}{ident}"
    if kind == "set_end":
        bits = [b for b in (ev.get("result") or vs, ev.get("reason")) if b]
        return "end: " + " · ".join(bits)
    if kind == "mark":
        return "Mark" + (f": {ev['note']}" if ev.get("note") else "") + (f" ({vs})" if vs else "")
    return EVENT_LABEL.get(kind, kind or "")


def set_info(p):
    """The set fields a page sends with Put on stream / setup / report / characters."""
    return {"setId": str(p["setId"]), "identifier": str(p.get("identifier") or "")[:12],
            "round": str(p.get("round") or "")[:80], "p1": str(p.get("p1") or "?")[:80],
            "p2": str(p.get("p2") or "?")[:80], "e1": p.get("e1"), "e2": p.get("e2"),
            "startedAt": p.get("startedAt") if isinstance(p.get("startedAt"), (int, float)) else None}


class Dock:
    def __init__(self):
        cfg = load_json(CONFIG_FILE, {})
        self.config = {**DEFAULT_CONFIG, **cfg}
        self.config["streamIds"] = {**DEFAULT_CONFIG["streamIds"], **(cfg.get("streamIds") or {})}
        if not self.config.get("setups"):
            self.config["setups"] = list(DEFAULT_CONFIG["setups"])
        ss = cfg.get("streamSetups") if isinstance(cfg.get("streamSetups"), dict) else DEFAULT_CONFIG["streamSetups"]
        self.config["streamSetups"] = {n: ss.get(n) if isinstance(ss.get(n), int) and ss.get(n) < len(self.config["setups"])
                                       else None for n in STREAMS}
        st = load_json(STATE_FILE, {})
        self.streams = {n: (st.get("streams") or {}).get(n) for n in STREAMS}  # what is on each recording
        # Which set is on each setup right now: {"0": {setId, identifier, round, p1, p2, e1, e2, since, seg}}
        self.on_setup = st.get("onSetup") or {}
        self.tournament = None
        self.cache = {}
        self.version = 0
        self.changed = threading.Condition()

    # -- change notifications (main dock <-> bracket page)
    def bump(self, drop_cache=True):
        with self.changed:
            self.version += 1
            if drop_cache:
                self.cache.clear()
            self.changed.notify_all()

    def wait_change(self, since, timeout=25):
        with self.changed:
            if since is not None:
                self.changed.wait_for(lambda: self.version != since, timeout=timeout)
            return self.version

    # -- bracket start blackout
    # When the bracket starts (offline events: the first set started or put on a setup does it)
    # or is restarted, start.gg returns no sets at all for the event for 40-80 s with 7 players
    # (measured 2026-11-10; longer with a real bracket), then every set comes back with a new id
    # ("preview_..." -> number). The docks used to go blank right then. Now:
    #  - the last list is kept on screen, flagged "rebuilding";
    #  - start / call / stream on a preview set are queued and sent with the new id once
    #    start.gg has it (sending the old id fails), and shown in the held list meanwhile.
    def bracket_starting(self):
        t = self.__dict__.get("starting_since")
        return bool(self.__dict__.get("rebuilding")) or bool(t and time.time() - t < 180)

    def lookup_set(self, set_id):
        for data in self.__dict__.get("last_good", {}).values():
            for s in (data.get("open") or []) + (data.get("done") or []) + (data.get("sets") or []):
                if str(s.get("id")) == str(set_id):
                    return s
        return None

    def queue_action(self, kind, set_id, v=None):
        s = self.lookup_set(set_id)
        if not s or len(s.get("slots") or []) != 2:
            raise ApiError("start.gg is still setting up the bracket. Try again in a minute.")
        with PENDING_LOCK:
            self.__dict__.setdefault("pending", []).append({
                "kind": kind, "setId": str(set_id), "identifier": s.get("identifier"),
                "ents": sorted(str(x.get("entrantId")) for x in s["slots"]),
                "v": {k: x for k, x in (v or {}).items() if k != "setId"}, "t": time.time()})
        self.bump(drop_cache=False)

    def flush_pending(self, sets):
        """start.gg has real ids again: send the queued actions to the matching sets."""
        with PENDING_LOCK:
            todo, self.__dict__["pending"] = self.__dict__.get("pending") or [], []
        left, sent = [], False
        for p in todo:
            if time.time() - p["t"] > 600:
                print(f"Dropped queued {p['kind']} for set {p['identifier']}: start.gg never came back with it.")
                continue
            hit = next((s for s in sets if s.get("identifier") == p["identifier"] and
                        sorted(str(x.get("entrantId")) for x in s.get("slots") or []) == p["ents"]), None)
            if not hit or str(hit["id"]).startswith("preview_"):
                left.append(p)
                continue
            try:
                gql(MUTATIONS[p["kind"]], {**p["v"], "setId": hit["id"]})
                sent = True
            except ApiError as e:
                print(f"Queued {p['kind']} for set {p['identifier']} failed: {e}")
        if left:
            with PENDING_LOCK:
                self.__dict__["pending"] = left + self.__dict__.get("pending", [])
        if sent:
            self.bump()

    def hold_last(self, key, data, sets):
        """Keep the last list while start.gg is blank (see above). sets: the sets in data."""
        good = self.__dict__.setdefault("last_good", {})
        waiting = self.__dict__.setdefault("rebuilding", set())
        if sets:
            good[key] = data
            preview = any(str(s.get("id")).startswith("preview_") for s in sets)
            if preview != self.__dict__.get("was_preview", {}).get(key):
                self.__dict__.setdefault("was_preview", {})[key] = preview
                self.__dict__.pop("hidden_sets", None)  # bracket started or restarted: bye sets changed
            if not preview:
                self.__dict__.pop("starting_since", None)
            if self.__dict__.get("pending"):
                self.flush_pending(sets)
            if key in waiting:  # back: tell the other page now instead of at its next poll
                waiting.discard(key)
                self.bump(drop_cache=False)
            return data
        if key not in good:
            return data  # never had sets for this event: it really is empty
        waiting.add(key)
        # Show what the dock did meanwhile: started -> Playing, called -> Called.
        started = {k for k, t in (self.__dict__.get("started") or {}).items() if time.time() - t < 300}
        queued = {p["setId"]: p["kind"] for p in self.__dict__.get("pending") or []}

        def mark(lst):
            out = []
            for s in lst:
                sid = str(s.get("id"))
                if s.get("state") in (1, 4, 6, 7) and (sid in started or queued.get(sid) == "start"):
                    s = {**s, "state": 2}
                elif s.get("state") in (1, 4, 7) and queued.get(sid) == "call":
                    s = {**s, "state": 6}
                out.append(s)
            return out
        held = {**good[key], "rebuilding": True}
        for k in ("open", "sets"):
            if k in held:
                held[k] = mark(held[k])
        return held

    def cached(self, key, ttl, fn):
        """Result of fn(), at most ttl seconds old. Pages that ask at the same moment (all three
        refresh together after every action) share ONE start.gg request instead of sending one
        each. If start.gg's rate limit is hit, the last result is served until it clears."""
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        with CACHE_LOCK:
            lock = self.__dict__.setdefault("fetch_locks", {}).setdefault(key, threading.Lock())
        with lock:
            hit = self.cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]  # another page fetched it while this one waited
            stale = self.__dict__.setdefault("stale", {})
            try:
                val = fn()
            except RateLimited:
                if key not in stale:
                    raise
                val = {**stale[key], "rateLimited": True} if isinstance(stale[key], dict) else stale[key]
                self.cache[key] = (time.time(), val)  # don't ask again for ttl seconds
                return val
            self.cache[key] = (time.time(), val)
            stale[key] = val
            return val

    def mark_started(self, set_id):
        """The dock started this set on start.gg. Starting a preview set starts the whole bracket."""
        self.__dict__.setdefault("started", {})[str(set_id)] = time.time()
        if str(set_id).startswith("preview_"):
            self.__dict__["starting_since"] = time.time()

    def save_state(self):
        save_json(STATE_FILE, {"streams": self.streams, "onSetup": self.on_setup})

    # -- timestamp log (one folder per tournament)
    def log_dir(self):
        slug = re.sub(r"[^a-z0-9-]", "", (self.config.get("tournamentSlug") or "").lower())
        return os.path.join(LOG_ROOT, slug or "no-tournament")

    def read_log(self):
        out = []
        try:
            with open(os.path.join(self.log_dir(), "log.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        except OSError:
            pass
        out.sort(key=lambda e: e.get("t") or 0)  # stable: same-second events keep file order
        return out

    def add_event(self, kind, stream, info=None, t=None, **extra):
        ev = {"id": str(time.time_ns()), "t": round(t or time.time(), 3), "stream": stream, "event": kind}
        for k in ("setId", "identifier", "round", "p1", "p2"):
            if info and info.get(k) not in (None, ""):
                ev[k] = info[k]
        ev.update({k: v for k, v in extra.items() if v not in (None, "")})
        folder = self.log_dir()
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.write_exports()
        return ev

    def delete_event(self, ev_id):
        with LOCK:
            events = self.read_log()
            keep = [e for e in events if e.get("id") != str(ev_id)]
            if len(keep) == len(events):
                raise ValueError("event not found")
            write_atomic(os.path.join(self.log_dir(), "log.jsonl"),
                         "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep).encode("utf-8"))
            self.write_exports()
        self.bump(drop_cache=False)

    def with_video_times(self, events):
        """Add 'video' (time into that stream's recording) from the last 'Recording started'."""
        rec = {}
        out = []
        for e in events:
            e = dict(e)
            if e.get("event") == "rec_start":
                rec[e.get("stream")] = e["t"]
            base = rec.get(e.get("stream"))
            e["video"] = video_time(e["t"] - base) if base is not None else ""
            out.append(e)
        return out

    def rec_starts(self, events=None):
        rec = {n: None for n in STREAMS}
        for e in events if events is not None else self.read_log():
            if e.get("event") == "rec_start" and e.get("stream") in rec:
                rec[e["stream"]] = e["t"]
        return rec

    def write_exports(self):
        """timestamps.csv (both recordings) and 'Recording N chapters.txt' (one per recording)."""
        folder = self.log_dir()
        os.makedirs(folder, exist_ok=True)
        events = self.with_video_times(self.read_log())
        chars = self.read_set_chars()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "clock_time", self.label().lower(), "event", "video_time", "round", "set", "player1", "player2",
                    "p1_characters", "p2_characters", "result", "reason", "note", "set_id", "unix_time"])
        for e in events:
            c1, c2 = self.chars_of(e, chars)
            w.writerow([day(e["t"]), clock(e["t"]), e.get("stream", ""), e.get("event", ""), e["video"],
                        e.get("round", ""), e.get("identifier", ""), e.get("p1", ""), e.get("p2", ""),
                        ", ".join(c1), ", ".join(c2),
                        e.get("result", ""), e.get("reason", ""), e.get("note", ""), e.get("setId", ""), e["t"]])
        write_atomic(os.path.join(folder, "timestamps.csv"), buf.getvalue().encode("utf-8-sig"))  # BOM: Excel
        name = (self.tournament or {}).get("name") or self.config.get("tournamentSlug") or "Tournament"
        for n in STREAMS:
            lines = [f"{name} · {self.slot(n)}",
                     "Left column = time into the recording, counted from when \"Rec started\" was pressed.",
                     "[Clock time] in brackets. If Rec started wasn't pressed, compare the clock times with the",
                     "recording's file name (OBS names files by the time recording started).", ""]
            mine = [e for e in events if e.get("stream") == n]
            for e in mine:
                if e.get("event") == "rec_start":
                    lines += ["", f"--- Recording started {clock(e['t'])} ({day(e['t'])}) ---"]
                indent = "    " if e.get("event") == "set_end" else ""
                lines.append(f"{e['video'] or '-:--:--':>8}  {indent}{describe(e, self.chars_of(e, chars))}  [{clock(e['t'])}]")
            if not mine:
                lines.append("(nothing logged yet)")
            write_atomic(os.path.join(folder, f"{self.slot(n)} chapters.txt"), ("\r\n".join(lines) + "\r\n").encode("utf-8-sig"))
        self.write_setup_exports(chars)

    def label(self):
        """'Recording' (default) or 'Stream': what the two OBS outputs are called."""
        return re.sub(r"[^\w -]", "", str(self.config.get("slotLabel") or "Recording")).strip()[:20] or "Recording"

    def slot(self, n):
        return f"{self.label()} {n}"

    # -- setups (named in the gear menu). Every setup is time-stamped, recorded or not; the two
    # recordings each capture one setup (streamSetups), and those stay in step with Put on stream.
    def setup_names(self):
        return [str(n) for n in self.config.get("setups") or []]

    def setup_label(self, idx):
        names = self.setup_names()
        return names[idx] if 0 <= idx < len(names) else f"Setup {idx + 1}"

    def stream_for_setup(self, idx):
        """Recording ("1"/"2") that captures setup idx, or None."""
        return next((n for n in STREAMS if self.config["streamSetups"].get(n) == idx), None)

    def read_setup_log(self):
        out = []
        try:
            with open(os.path.join(self.log_dir(), "setups.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        except OSError:
            pass
        out.sort(key=lambda e: e.get("t") or 0)
        return out

    def add_setup_event(self, kind, idx, info=None, t=None, **extra):
        ev = {"id": str(time.time_ns()), "t": round(t or time.time(), 3), "setup": idx + 1,
              "setupName": self.setup_label(idx), "event": kind}
        rec = self.stream_for_setup(idx)
        if rec:
            ev["stream"] = rec
        for k in ("setId", "identifier", "round", "p1", "p2", "startedAt", "seg"):
            if info and info.get(k) not in (None, ""):
                ev[k] = info[k]
        ev.update({k: v for k, v in extra.items() if v not in (None, "")})
        folder = self.log_dir()
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "setups.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.__dict__.pop("past_cache", None)
        self.write_setup_exports()
        return ev

    # A set keeps ONE segment (one start time) even if its result is reset and reported again:
    # the log is append-only, so corrections are extra lines that refer to the segment ("seg"):
    #   set_end again   = corrected result; the LAST set_end of a seg counts (its t = the first end's t)
    #   setup_fix       = the segment was really on another setup (picked at the re-report)
    @staticmethod
    def segments(events):
        """Resolved view of the log: seg id -> {"start", "end" (or None), "setup", "setupName"}."""
        segs = {}
        for e in events:
            kind, seg = e.get("event"), e.get("seg")
            if kind == "on_setup":
                segs[e["id"]] = {"start": e, "end": None, "setup": e.get("setup"), "setupName": e.get("setupName")}
            elif seg in segs and kind == "set_end":
                segs[seg]["end"] = e
            elif seg in segs and kind == "setup_fix":
                segs[seg].update(setup=e.get("setup"), setupName=e.get("setupName"))
        return segs

    def past_segments(self):
        """Finished segments by start.gg set id: {setId: {"seg", "setup" (index), "end"}} (latest wins)."""
        key = self.log_dir()
        hit = self.__dict__.get("past_cache")
        if hit and hit[0] == key:
            return hit[1]
        out = {}
        for seg, s in self.segments(self.read_setup_log()).items():
            sid = str((s["end"] or {}).get("setId") or "")
            if sid and not sid.startswith("preview_") and isinstance(s["setup"], int):
                out[sid] = {"seg": seg, "setup": s["setup"] - 1, "end": s["end"]}
        self.__dict__["past_cache"] = (key, out)
        return out

    def write_setup_exports(self, chars=None):
        """setups.csv (every event) and 'Setup times.txt' (one block per setup, start - end)."""
        folder = self.log_dir()
        events = self.read_setup_log()
        if not events:
            return
        chars = self.read_set_chars() if chars is None else chars
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "clock_time", "setup", "setup_name", "recorded_on", "event", "round", "set", "player1",
                    "player2", "p1_characters", "p2_characters", "result", "reason", "note", "set_id",
                    "startgg_started", "unix_time"])
        for e in events:
            st = e.get("startedAt")
            c1, c2 = self.chars_of(e, chars)
            w.writerow([day(e["t"]), clock(e["t"]), e.get("setup", ""), e.get("setupName", ""),
                        self.slot(e["stream"]) if e.get("stream") else "", e.get("event", ""),
                        e.get("round", ""), e.get("identifier", ""), e.get("p1", ""), e.get("p2", ""),
                        ", ".join(c1), ", ".join(c2), e.get("result", ""), e.get("reason", ""), e.get("note", ""),
                        e.get("setId", ""), clock(st) if st else "", e["t"]])
        write_atomic(os.path.join(folder, "setups.csv"), buf.getvalue().encode("utf-8-sig"))
        name = (self.tournament or {}).get("name") or self.config.get("tournamentSlug") or "Tournament"
        lines = [f"{name} · sets per setup (clock time; video times are in the {self.label()} N chapters)", ""]
        # One line per segment, with corrections applied (last result, corrected setup).
        segs = list(self.segments(events).values())
        for num in sorted({s["setup"] for s in segs if s["setup"]}):
            raw = [e for e in events if e.get("setup") == num]
            rec = raw[-1].get("stream")
            lines += [f"== {raw[-1].get('setupName') or f'Setup {num}'}{f' (recorded: {self.slot(rec)})' if rec else ' (not recorded)'} =="]
            for sg in (s for s in segs if s["setup"] == num):
                start, end = sg["start"], sg["end"]
                fixed = start.get("setup") != num
                ident = f" ({start['identifier']})" if start.get("identifier") else ""
                c1, c2 = self.chars_of(start, chars)
                mins = f" [{round((end['t'] - start['t']) / 60)} min]" if end else ""
                lines.append(f"  {clock(start['t'])} - {clock(end['t']) if end else '(playing)'}{mins}  "
                             f"{start.get('round') or 'Set'}{ident}: {with_chars(start.get('p1', '?'), c1)} vs "
                             f"{with_chars(start.get('p2', '?'), c2)}"
                             f"{'  ->  ' + (end.get('result') or end.get('reason') or '') if end else ''}"
                             f"{'  [setup picked at report]' if start.get('note') else ''}"
                             f"{'  [setup corrected, was ' + str(start.get('setupName')) + ']' if fixed else ''}")
            lines.append("")
        write_atomic(os.path.join(folder, "Setup times.txt"), ("\r\n".join(lines) + "\r\n").encode("utf-8-sig"))

    def end_setup(self, idx, reason, t=None, result=""):
        cur = self.on_setup.pop(str(idx), None)
        if not cur:
            return None
        return self.add_setup_event("set_end", idx, cur, t=t, reason=reason, result=result)

    def setup_of(self, set_id, identifier=None, entrants=()):
        for k, cur in self.on_setup.items():
            if self.same_set(cur, set_id, identifier, entrants):
                return int(k)
        return None

    def _on_setup(self, idx, info, now, note=""):
        """Log a set starting on setup idx (caller holds LOCK): ends what was there and the
        set's segment on another setup."""
        ents = [info.get("e1"), info.get("e2")]
        if self.same_set(self.on_setup.get(str(idx)), info["setId"], info.get("identifier"), ents):
            return None
        if self.on_setup.get(str(idx)):
            self.end_setup(idx, f"next set on {self.setup_label(idx)}", now)
        other = self.setup_of(info["setId"], info.get("identifier"), ents)
        if other is not None:
            self.end_setup(other, f"moved to {self.setup_label(idx)}", now)
        ev = self.add_setup_event("on_setup", idx, info, t=now, note=note)
        self.on_setup[str(idx)] = {**info, "since": now, "seg": ev["id"]}
        return ev

    def assign_setup(self, p):
        """Put on setup. A recorded setup = Put on stream N. Otherwise: time-stamp it, take the
        set off a recording if it was on one (moved), then mark it in progress on start.gg."""
        try:
            idx = int(p.get("setup"))
        except (TypeError, ValueError):
            raise ValueError("bad setup") from None
        if not (0 <= idx < len(self.setup_names())) or not p.get("setId"):
            raise ValueError("bad setup or set")
        rec = self.stream_for_setup(idx)
        if rec:
            return self.put_on_stream({**p, "stream": rec})
        info = set_info(p)
        with LOCK:
            now = time.time()
            ev = self._on_setup(idx, info, now)
            if not ev:
                return {"ok": True, "already": True}
            for n in STREAMS:
                if self.same_set(self.streams.get(n), info["setId"], info["identifier"], [info["e1"], info["e2"]]):
                    self.end_slot(n, f"moved to {self.setup_label(idx)} (not recorded)", now)
            self.save_state()
        self.bump(drop_cache=False)
        warning, queued = "", False
        if p.get("state") != 2:
            try:
                if info["setId"].startswith("preview_") and self.bracket_starting():
                    self.queue_action("start", info["setId"])  # old id is dead; sent once start.gg is back
                    queued = True
                else:
                    gql(MUTATIONS["start"], {"setId": info["setId"]})
                    self.mark_started(info["setId"])
                    self.bump()
            except ApiError as e:
                warning = str(e)
        return {"ok": True, "clock": clock(ev["t"]), "warning": warning, "queued": queued}

    def clear_setup(self, p):
        try:
            idx = int(p.get("setup"))
        except (TypeError, ValueError):
            raise ValueError("bad setup") from None
        with LOCK:
            cur = self.on_setup.get(str(idx))
            ev = self.end_setup(idx, "taken off by hand")
            rec = self.stream_for_setup(idx)
            if cur and rec and self.same_set(self.streams.get(rec), cur.get("setId"), cur.get("identifier"),
                                             [cur.get("e1"), cur.get("e2")]):
                self.end_slot(rec, "taken off by hand")
            self.save_state()
        if not ev:
            raise ValueError(f"Nothing is on {self.setup_label(idx)}.")
        self.bump(drop_cache=False)
        return {"ok": True, "clock": clock(ev["t"])}

    def set_setups(self, payload):
        names = [str(n).strip()[:40] for n in (payload.get("names") or [])][:SETUPS_MAX]
        names = [n or f"Setup {i + 1}" for i, n in enumerate(names)] or ["Setup 1"]
        rec = payload.get("streamSetups") or {}
        new_rec = {}
        for n in STREAMS:
            v = rec.get(n, self.config["streamSetups"].get(n))
            v = int(v) if isinstance(v, int) or (isinstance(v, str) and v.isdigit()) else None
            new_rec[n] = v if v is not None and v < len(names) else None
        if new_rec["1"] is not None and new_rec["1"] == new_rec["2"]:
            raise ValueError(f"{self.slot('1')} and {self.slot('2')} can't record the same setup.")
        with LOCK:
            for k in list(self.on_setup):
                if int(k) >= len(names):
                    self.end_setup(int(k), "setup removed in settings")
            self.config["setups"] = names
            self.config["streamSetups"] = new_rec
            save_json(CONFIG_FILE, self.config)
            self.save_state()
        self.bump(drop_cache=False)

    def setups_view(self):
        return {"setups": [{"index": i, "name": n, "on": self.on_setup.get(str(i)), "stream": self.stream_for_setup(i)}
                           for i, n in enumerate(self.setup_names())],
                "streamSetups": self.config["streamSetups"],
                # setId -> setup index a finished set was logged on (pre-picked when it is re-reported)
                "past": {sid: s["setup"] for sid, s in self.past_segments().items()}}

    # -- characters (start.gg's cast; per tournament for titles, per player for pre-fill)
    def chars_file(self):
        return os.path.join(self.log_dir(), "characters.json")

    def read_set_chars(self):
        return load_json(self.chars_file(), {})

    @staticmethod
    def chars_of(ev, chars):
        """(p1 chars, p2 chars) for a logged set, by id or set letter (preview ids change)."""
        if not ev.get("setId"):
            return [], []
        c = chars.get(str(ev["setId"])) or next(
            (x for x in chars.values() if ev.get("identifier") and x.get("identifier") == ev.get("identifier")), None)
        if not c:
            return [], []
        # Stored in the set's slot order; flip if this event lists the players the other way round.
        if ev.get("p1") and ev.get("p1") == c.get("p2") and ev.get("p2") != c.get("p2"):
            return c.get("chars2") or [], c.get("chars1") or []
        return c.get("chars1") or [], c.get("chars2") or []

    def cast(self):
        return [c.get("name") for c in (load_json(CAST_FILE, {}).get("characters") or []) if c.get("name")]

    def players_view(self):
        """player id -> {tag, top: characters by how often they were played (most recent first on ties)}."""
        out = {}
        for pid, p in (load_json(PLAYERS_FILE, {}).get("players") or {}).items():
            count, last = {}, {}
            for i, s in enumerate(p.get("sets") or []):
                for c in s.get("chars") or []:
                    count[c] = count.get(c, 0) + 1
                    last[c] = i
            out[pid] = {"tag": p.get("tag"), "top": sorted(count, key=lambda c: (-count[c], -last[c]))}
        return out

    def save_chars(self, p, source="dock"):
        """Characters for one set: per tournament (titles) and per player (pre-fill next time)."""
        valid = set(self.cast())
        clean = lambda xs: [str(x) for x in (xs or []) if str(x) in valid][:CHARS_MAX]
        c1, c2 = clean(p.get("chars1")), clean(p.get("chars2"))
        if not (c1 or c2):
            return False
        info = set_info(p)
        with LOCK:
            chars = self.read_set_chars()
            for k in [k for k, v in chars.items() if info["identifier"] and v.get("identifier") == info["identifier"]]:
                chars.pop(k)  # same set under an old (preview) id
            chars[info["setId"]] = {"identifier": info["identifier"], "round": info["round"], "p1": info["p1"],
                                    "p2": info["p2"], "chars1": c1, "chars2": c2, "t": round(time.time())}
            os.makedirs(self.log_dir(), exist_ok=True)
            save_json(self.chars_file(), chars)
            data = load_json(PLAYERS_FILE, {})
            players = data.setdefault("players", {})
            slug = self.config.get("tournamentSlug") or ""
            for pid, tag, cs in ((p.get("pid1"), p.get("tag1"), c1), (p.get("pid2"), p.get("tag2"), c2)):
                if not cs:
                    continue
                tag = str(tag or "")[:80]
                key = str(pid) if pid else "tag:" + re.sub(r"[^a-z0-9]", "", tag.lower())
                if key == "tag:":
                    continue  # no player id and no tag: nothing to file it under
                pl = players.setdefault(key, {"tag": tag, "sets": []})
                pl["tag"] = tag or pl.get("tag")
                pl["sets"] = [s for s in pl.get("sets") or []
                              if not (s.get("tournament") == slug and s.get("set") == (info["identifier"] or info["setId"]))]
                pl["sets"].append({"tournament": slug, "set": info["identifier"] or info["setId"], "round": info["round"],
                                   "chars": cs, "t": round(time.time()), "source": source})
            data["updated"] = time.strftime("%Y-%m-%d %H:%M")
            save_json(PLAYERS_FILE, data)
            self.write_exports()
        self.bump(drop_cache=False)
        return True

    # -- what's on each recording
    def on_stream_ids(self):
        return {n: (self.streams.get(n) or {}).get("setId") for n in STREAMS}

    def end_slot(self, n, reason, t=None, result=""):
        cur = self.streams.get(n)
        if not cur:
            return None
        ev = self.add_event("set_end", n, cur, t=t, reason=reason, result=result)
        self.streams[n] = None
        return ev

    def put_on_stream(self, p):
        n = str(p.get("stream"))
        if n not in STREAMS or not p.get("setId"):
            raise ValueError("bad stream or set")
        info = set_info(p)
        with LOCK:
            cur = self.streams.get(n)
            same = lambda c: self.same_set(c, info["setId"], info["identifier"], [info["e1"], info["e2"]])
            idx = self.config["streamSetups"].get(n)
            if same(cur):
                if idx is not None and not same(self.on_setup.get(str(idx))):
                    self._on_setup(idx, info, time.time())  # setup log catches up (e.g. after a settings change)
                    self.save_state()
                return {"ok": True, "already": True}
            now = time.time()
            if cur:
                self.end_slot(n, f"next set on {self.slot(n).lower()}" + (f" ({info['identifier']})" if info["identifier"] else ""), now)
            for m in STREAMS:
                if m != n and same(self.streams.get(m)):
                    self.end_slot(m, f"moved to {self.slot(n).lower()}", now)
            ev = self.add_event("on_stream", n, info, t=now)
            self.streams[n] = {**info, "since": now}
            if idx is not None:  # the setup this recording captures gets the set too
                self._on_setup(idx, info, now)
            self.save_state()
        self.bump(drop_cache=False)
        # start.gg (after the timestamp is safe): assign the stream if one is picked, mark in progress.
        warnings, changed, queued = [], False, False
        sid = self.config["streamIds"].get(n)
        # While start.gg sets up the bracket the old (preview) id is dead: queue, send with the new id.
        hold = info["setId"].startswith("preview_") and self.bracket_starting()
        try:
            if sid and str(p.get("currentStreamId")) != str(sid):
                if hold:
                    self.queue_action("stream", info["setId"], {"streamId": sid})
                    queued = True
                else:
                    gql(MUTATIONS["stream"], {"setId": info["setId"], "streamId": sid})
                    changed = True
            if p.get("state") != 2:
                if hold:
                    self.queue_action("start", info["setId"])
                    queued = True
                else:
                    gql(MUTATIONS["start"], {"setId": info["setId"]})
                    self.mark_started(info["setId"])
                    changed = True
        except ApiError as e:
            warnings.append(str(e))
        if changed:
            self.bump()
        return {"ok": True, "clock": clock(ev["t"]), "warning": "; ".join(warnings), "queued": queued}

    def slot_action(self, p):
        n, kind = str(p.get("stream")), p.get("action")
        if n not in STREAMS:
            raise ValueError("bad stream")
        with LOCK:
            if kind == "rec":
                ev = self.add_event("rec_start", n)
            elif kind == "end":
                cur = self.streams.get(n)
                ev = self.end_slot(n, "ended by hand")
                if not ev:
                    raise ValueError(f"Nothing is on {self.slot(n).lower()}.")
                idx = self.setup_of(cur.get("setId"), cur.get("identifier"), [cur.get("e1"), cur.get("e2")])
                if idx is not None:
                    self.end_setup(idx, "set over (by hand)", ev["t"])
                self.save_state()
            elif kind == "mark":
                ev = self.add_event("mark", n, self.streams.get(n), note=str(p.get("note") or "")[:120])
            else:
                raise ValueError("unknown action")
        self.bump(drop_cache=False)
        return {"ok": True, "clock": clock(ev["t"])}

    @staticmethod
    def same_set(cur, set_id, identifier=None, entrants=()):
        """Is this the set on a recording? By id, or by set letter + both players: start.gg's
        "preview_..." ids (bracket not started yet) change once the bracket starts."""
        if not cur:
            return False
        if str(cur.get("setId")) == str(set_id):
            return True
        mine = {str(cur.get("e1")), str(cur.get("e2"))}
        return (bool(identifier) and identifier == cur.get("identifier") and "None" not in mine
                and mine == {str(e) for e in entrants})

    def _follow(self, cur, sets, full):
        """Find the set a recording / setup entry is about. -> (set or None, gone, id_changed, unresolved).
        gone = the bracket was restarted on start.gg (e.g. reseeded for a late arrival) and no
        longer has this set: it starts fresh, with a new entry when it is put on again."""
        was_preview = str(cur["setId"]).startswith("preview_")
        mine = {str(cur.get("e1")), str(cur.get("e2"))}
        s = next((x for x in sets if str(x["id"]) == str(cur["setId"])), None)
        gone = id_changed = unresolved = False
        if s:
            # Same id but other players: a preview id reused after a restart + reseed.
            theirs = {str(sl.get("entrantId")) for sl in s["slots"]}
            gone = "None" not in mine and "None" not in theirs and len(theirs) == 2 and theirs != mine
        else:
            s = next((x for x in sets if self.same_set(cur, x["id"], x.get("identifier"),
                                                       [sl.get("entrantId") for sl in x["slots"]])), None)
            if s and not was_preview:
                gone = True  # a numeric id never changes: same pairing, new id = restarted bracket
            elif s:
                cur["setId"] = str(s["id"])  # bracket started: preview id -> real id
                id_changed = True
            elif full:
                # Not in the bracket any more. Wait 45 s before believing it: right after a
                # bracket start, start.gg's list can be incomplete for a moment.
                gone = time.time() - cur.setdefault("missingSince", time.time()) > 45
            else:
                unresolved = True
        if s:
            cur.pop("missingSince", None)
        return s, gone, id_changed, unresolved

    def check_finished(self, sets, full=False, rebuilding=False):
        """Follow the sets on the recordings and setups: pick up a new set id, end the segment of
        a set that is now done on start.gg (reported anywhere), and end sets a restarted bracket
        no longer has (reason "bracket restarted").
        full: sets is the whole bracket. Returns True if an entry wasn't found in a partial list."""
        changed = unresolved = False
        if not sets or rebuilding:  # start.gg blank / held list: nothing can be judged
            return False
        with LOCK:
            for n in STREAMS:
                cur = self.streams.get(n)
                if not cur:
                    continue
                s, gone, ch, un = self._follow(cur, sets, full)
                changed, unresolved = changed or ch, unresolved or un
                if gone:
                    self.__dict__.pop("hidden_sets", None)
                    self.end_slot(n, "bracket restarted")
                    changed = True
                elif s and s.get("state") == 3:
                    t = s.get("completedAt") or time.time()
                    t = min(max(t, cur.get("since") or t), time.time())
                    self.end_slot(n, "reported", t, result_text(s))
                    changed = True
            for k, cur in list(self.on_setup.items()):
                s, gone, ch, un = self._follow(cur, sets, full)
                changed, unresolved = changed or ch, unresolved or un
                if gone:
                    self.__dict__.pop("hidden_sets", None)
                    self.end_setup(int(k), "bracket restarted")
                    changed = True
                elif s and s.get("state") == 3:
                    t = s.get("completedAt") or time.time()
                    t = min(max(t, cur.get("since") or t), time.time())
                    self.end_setup(int(k), "reported", t, result_text(s))
                    changed = True
            if changed:
                self.save_state()
        if changed:
            self.bump(drop_cache=False)
        return unresolved

    # -- tournament
    def load_tournament(self, refresh_link=False):
        slug = self.config.get("tournamentSlug")
        # Unless a slug was pinned, look up the latest tournament once per start (new week = new slug).
        if refresh_link or not slug or (not self.config.get("pinSlug") and not self.tournament):
            try:
                link = str(self.config.get("shortLink") or "").strip()
                if not link:
                    raise ApiError("No tournament yet: type its slug in the gear menu and click Load slug, or put "
                                   "your series' start.gg short link in dock_config.json (\"shortLink\").")
                slug = resolve_short_link(link)
            except ApiError:
                if not slug:
                    raise
        t = gql(Q_TOURNAMENT, {"slug": slug}).get("tournament")
        if not t:
            raise ApiError(f"Tournament '{slug}' not found.")
        if slug != self.config.get("tournamentSlug"):
            self.config["eventId"] = None
            with LOCK:  # last week's sets aren't on stream / on a setup any more
                self.streams = {n: None for n in STREAMS}
                self.on_setup = {}
                self.save_state()
        self.config["tournamentSlug"] = slug
        # Protocol runs Melee + Ultimate; this dock only uses the Ultimate events.
        ult = [e for e in t.get("events") or [] if (e.get("videogame") or {}).get("id") == ULTIMATE_ID]
        if not ult:
            raise ApiError(f"'{slug}' has no Ultimate event.")
        ult.sort(key=lambda e: ("doubles" not in (e.get("name") or "").lower(), e.get("numEntrants") or 0),
                 reverse=True)  # singles first, then the biggest
        t["events"] = ult
        if str(self.config.get("eventId")) not in [str(e["id"]) for e in ult]:
            self.config["eventId"] = ult[0]["id"]
        known = {str(s["id"]) for s in t.get("streams") or []}
        for n in STREAMS:  # a stream picked for another tournament doesn't exist here
            if self.config["streamIds"].get(n) and str(self.config["streamIds"][n]) not in known:
                self.config["streamIds"][n] = None
        save_json(CONFIG_FILE, self.config)
        self.tournament = t
        return t

    def _event_id(self):
        if not self.tournament:
            self.load_tournament()
        eid = self.config.get("eventId")
        if not eid:
            raise ApiError("No Ultimate event found in this tournament.")
        return eid

    def _header(self, eid):
        return {
            "tournament": {k: self.tournament.get(k) for k in ("name", "slug", "state")},
            "events": [{"id": e["id"], "name": e["name"], "numEntrants": e.get("numEntrants")} for e in self.tournament.get("events") or []],
            "eventId": eid,
            "streams": self.tournament.get("streams") or [],
            "streamIds": self.config["streamIds"],
            "fetchedAt": time.time(),
        }

    def sets(self):
        """Open sets + recent results for Home, built from the same whole-bracket data the bracket
        pages use. start.gg's lists filtered by state (the old source) trail the bracket by several
        seconds after an action, so Home used to lag behind the other pages; it also cost two
        extra requests per refresh. Now all pages share one fetch and always agree."""
        b = self.bracket()  # cached, held while start.gg is blank, seeds; follows sets on recordings / setups
        sets = b["sets"]
        ready = lambda s: len(s["slots"]) == 2 and all(x["entrantId"] for x in s["slots"])
        order = lambda s: (abs(s.get("roundNum") or 0), len(s.get("identifier") or ""), s.get("identifier") or "")
        open_list = sorted((s for s in sets if s.get("state") != 3 and ready(s)), key=order)
        done = sorted((s for s in sets if s.get("state") == 3), key=lambda s: s.get("completedAt") or 0, reverse=True)[:15]
        out = {k: v for k, v in b.items() if k not in ("sets", "finalsLabel", "finalsFrom")}
        return {**out, "open": open_list, "done": done}

    def bracket(self):
        eid = self._event_id()

        def fetch():
            out, page = [], 1
            while True:
                ev = gql(Q_BRACKET, {"eventId": eid, "page": page}).get("event") or {}
                sets = ev.get("sets") or {}
                out += [simplify_set(s) for s in sets.get("nodes") or []]
                total = (sets.get("pageInfo") or {}).get("totalPages") or 1
                if page >= total or page >= max_pages:
                    if total > max_pages and not getattr(self, "_warned_pages", False):
                        self._warned_pages = True
                        print(f"Bracket has {total} pages of 25 sets; only {max_pages} are read. "
                              f'Raise "maxBracketPages" in dock_config.json.')
                    break
                page += 1
            self.resolve_byes(out)
            return {**self._header(eid), "sets": out}
        # Every page counts against start.gg's limit: with many devices open, a longer shared cache
        # keeps a big bracket under it.
        max_pages = max(1, int(self.config.get("maxBracketPages") or 20))
        ttl = max(5, float(self.config.get("bracketCacheSeconds") or 5))
        data = self.cached(("bracket", eid), ttl, fetch)
        data = self.hold_last(("bracket", eid), data, data["sets"])
        self.fill_seeds(eid, data["sets"])
        self.check_finished(data["sets"], full=True, rebuilding=bool(data.get("rebuilding")))
        return data

    def fill_seeds(self, eid, sets):
        """Seed numbers for players in later rounds (start.gg only gives them on first-round slots).
        Remembers entrant -> seed per event; sets are updated in place."""
        known = self.__dict__.setdefault("seeds", {}).setdefault(str(eid), {})
        for s in sets:
            for sl in s["slots"]:
                if sl.get("entrantId") and sl.get("seed"):
                    known[str(sl["entrantId"])] = sl["seed"]
        for s in sets:
            for sl in s["slots"]:
                if sl.get("entrantId") and not sl.get("seed"):
                    sl["seed"] = known.get(str(sl["entrantId"]))

    def resolve_byes(self, sets):
        """start.gg leaves "X vs bye" sets out of the list; follow them to the visible source set."""
        visible = {str(s["id"]) for s in sets}
        cache = self.__dict__.setdefault("hidden_sets", {})
        for _ in range(4):
            missing = {str(sl["prereqId"]) for s in sets for sl in s["slots"]
                       if sl.get("prereqType") == "set" and sl.get("prereqId") is not None
                       and str(sl["prereqId"]) not in visible and str(sl["prereqId"]) not in cache}
            missing |= {str(sl["prereqId"]) for h in cache.values() for sl in (h or {}).get("slots", [])
                        if sl.get("prereqType") == "set" and str(sl.get("prereqId")) not in visible
                        and str(sl.get("prereqId")) not in cache}
            if not missing:
                break
            ids = sorted(missing)[:30]
            q = "query {" + " ".join(
                f's{i}: set(id: {json.dumps(sid)}) {{ id identifier slots {{ prereqType prereqId prereqPlacement }} }}'
                for i, sid in enumerate(ids)) + "}"
            try:
                d = gql(q)
            except ApiError:
                break
            for i, sid in enumerate(ids):
                cache[sid] = d.get(f"s{i}")

        def follow(pid, placement, depth=0):
            pid = str(pid)
            if pid in visible:
                return pid, placement
            h = cache.get(pid)
            if not h or depth > 5 or placement != 1:
                return None
            real = [sl for sl in h.get("slots") or [] if sl.get("prereqType") != "bye"]
            if len(real) == 1 and real[0].get("prereqType") == "set":
                return follow(real[0]["prereqId"], real[0].get("prereqPlacement"), depth + 1)
            return None

        for s in sets:
            for sl in s["slots"]:
                if sl.get("prereqType") == "set" and str(sl.get("prereqId")) not in visible:
                    hit = follow(sl["prereqId"], sl.get("prereqPlacement"))
                    if hit:
                        sl["prereqId"], sl["prereqPlacement"] = hit

    # -- start.gg actions
    def action(self, payload):
        kind = payload.get("action")
        set_id = payload.get("setId")
        if kind not in MUTATIONS or kind == "stream" or not set_id:
            raise ValueError("unknown action")
        v = {"setId": set_id}
        result = ""
        if kind == "report":
            e1, e2 = payload.get("entrant1"), payload.get("entrant2")
            n1, n2 = str(payload.get("name1") or "?"), str(payload.get("name2") or "?")
            s1, s2 = int(payload.get("score1") or 0), int(payload.get("score2") or 0)
            if payload.get("dqLoser"):
                loser = payload["dqLoser"]
                if loser not in (e1, e2):
                    raise ValueError("bad DQ entrant")
                v.update(winnerId=e2 if loser == e1 else e1, isDQ=True)
                result = f"DQ: {n1 if loser == e1 else n2}"
            else:
                if s1 == s2:
                    raise ValueError("Scores are tied; a set needs a winner.")
                winner = e1 if s1 > s2 else e2
                games, n = [], 1
                lose_id, lose_n = (e2, s2) if winner == e1 else (e1, s1)
                for _ in range(lose_n):
                    games.append({"winnerId": lose_id, "gameNum": n}); n += 1
                for _ in range(max(s1, s2)):
                    games.append({"winnerId": winner, "gameNum": n}); n += 1
                v.update(winnerId=winner, isDQ=False, gameData=games)
                result = f"{n1} {s1}-{s2} {n2}" if s1 > s2 else f"{n2} {s2}-{s1} {n1}"
        if str(set_id).startswith("preview_") and self.bracket_starting():
            if kind in ("start", "call"):
                self.queue_action(kind, set_id, v)
                return {"queued": True}
            raise ApiError("start.gg is still setting up the bracket. Try again in a minute.")
        out = gql(MUTATIONS[kind], v)
        if kind == "start":  # shown as playing if start.gg goes blank while it starts the bracket
            self.mark_started(set_id)
        if kind == "report":
            try:
                self.after_report(payload, result)
            except Exception as e:  # the report went through; don't fail it over the logs
                print(f"Timestamps/characters not updated after report: {e}")
        self.bump()
        return out

    def after_report(self, payload, result):
        """End the set's recording + setup segments. A set never put on a setup gets the setup
        picked in the report dialog (start = start.gg's startedAt when known). Save characters."""
        ents = [payload.get("entrant1"), payload.get("entrant2")]
        info = set_info({**payload, "e1": ents[0], "e2": ents[1], "p1": payload.get("name1"), "p2": payload.get("name2")})
        now = time.time()
        with LOCK:
            for n in STREAMS:
                if self.same_set(self.streams.get(n), info["setId"], info["identifier"], ents):
                    self.end_slot(n, "reported", result=result)
            idx = self.setup_of(info["setId"], info["identifier"], ents)
            past = self.past_segments().get(info["setId"]) if idx is None else None
            if past:
                # Reported before (result was reset): keep the segment and its times. Only the
                # result changes, and the setup if another one is picked this time.
                try:
                    new = int(payload["setup"]) if payload.get("setup") not in (None, "") else past["setup"]
                except (TypeError, ValueError):
                    new = past["setup"]
                if 0 <= new < len(self.setup_names()):
                    seg_info = {**info, "seg": past["seg"]}
                    if new != past["setup"]:
                        self.add_setup_event("setup_fix", new, seg_info, t=now,
                                             note=f"setup corrected at re-report (was {past['end'].get('setupName')})")
                    self.add_setup_event("set_end", new, seg_info, t=past["end"].get("t") or now,
                                         reason="re-reported in dock", result=result,
                                         note=f"result corrected at {clock(now)}; end time kept from the first report")
            elif idx is None and payload.get("setup") not in (None, ""):
                try:
                    idx = int(payload["setup"])
                except (TypeError, ValueError):
                    idx = None
                if idx is not None and 0 <= idx < len(self.setup_names()):
                    st = info.get("startedAt")
                    t = st if st and st < now else now
                    self._on_setup(idx, info, t, note="setup picked at report" +
                                   ("; start = start.gg start time" if t != now else "; start unknown"))
                else:
                    idx = None
            if idx is not None:
                self.end_setup(idx, "reported in dock", now, result)
            self.save_state()
        if payload.get("chars1") or payload.get("chars2"):
            self.save_chars({**payload, **info})


DOCK = None


def ui_version():
    """Changes whenever a page file is edited, so open docks reload themselves."""
    try:
        return str(max(os.path.getmtime(os.path.join(STATIC, f)) for f in os.listdir(STATIC)))
    except (OSError, ValueError):
        return "0"


# ---------------------------------------------------------------- HTTP

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".png": "image/png", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "UltimateDock/1.0"

    def log_message(self, fmt, *args):
        line = " ".join(map(str, args))
        if re.search(r"/api/(sets|bracket|changes|state|log)\b", line) and " 200 " in line + " ":
            return  # don't spam the window with routine polling
        sys.stderr.write("%s  %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def host_ok(self):
        # This PC: only "localhost" names (stops DNS-rebinding tricks from websites). A LAN device that
        # passed lan_gate (PIN) may use any address for the hub.
        if getattr(self, "role", "local") in ("full", "view"):
            return True
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    # -- LAN access (lan.py; off unless "lan" + "lanPin" are set in dock_config.json)
    def lan_gate(self, u):
        """Sets self.role ('local' / 'full' / 'view'). Returns True if the request was answered here."""
        self.role = LAN.role(self)
        if self.role is not None:
            return False
        if not LAN.on:
            self.send(403, {"error": "forbidden"})
        elif u.path == "/login":
            nxt = urllib.parse.parse_qs(u.query).get("next", ["/"])[0]
            self.send(200, LAN.login_page(nxt), "text/html; charset=utf-8")
        elif u.path.startswith("/api/"):
            self.send(403, {"error": "PIN needed: reload the page"})
        else:
            self.redirect("/login?next=" + urllib.parse.quote(u.path + ("?" + u.query if u.query else "")))
        return True

    def redirect(self, where, cookie=None):
        self.send_response(303)
        self.send_header("Location", where)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_login(self):
        form = lanmod.read_form(self)
        nxt = form.get("next") or "/"
        nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"
        role = LAN.check_pin(self.client_address[0], form.get("pin"))
        if role in ("full", "view"):
            print(f"LAN: {self.client_address[0]} signed in ({role})")
            return self.redirect(nxt, LAN.cookie_header(role))
        msg = "Too many tries: wait a minute." if role == "wait" else "Wrong PIN."
        return self.send(403, LAN.login_page(nxt, msg), "text/html; charset=utf-8")

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def api_guard(self):
        # Custom header => other websites can't call the API (no CORS preflight answer).
        if not self.host_ok() or self.headers.get("X-Dock") != "1":
            self.send(403, {"error": "forbidden"})
            return False
        return True

    def serve_static(self, rel):
        path = os.path.realpath(os.path.join(STATIC, urllib.parse.unquote(rel)))
        if not path.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(path):
            return self.send(404, {"error": "not found"})
        with open(path, "rb") as f:
            data = f.read()
        self.send(200, data, MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))

    def state(self):
        events = DOCK.read_log()
        return {"config": public_config(DOCK.config), "access": getattr(self, "role", "local"), "streams": DOCK.streams, "recStart": DOCK.rec_starts(events), **DOCK.setups_view(),
                "tokenSet": bool(get_token()), "logDir": DOCK.log_dir(), "uiVersion": ui_version()}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if self.lan_gate(u):
            return None
        if not self.host_ok():
            return self.send(403, {"error": "forbidden"})
        if u.path in ("/", "/index.html"):
            return self.serve_static("index.html")
        if u.path in ("/bracket", "/bracket/", "/bracket.html"):
            return self.serve_static("bracket.html")
        if u.path in ("/active", "/active/", "/active.html"):
            return self.serve_static("active.html")
        if u.path.startswith("/static/"):
            return self.serve_static(u.path[len("/static/"):])
        if not u.path.startswith("/api/"):
            return self.send(404, {"error": "not found"})
        if not self.api_guard():
            return None
        try:
            if u.path == "/api/state":
                return self.send(200, self.state())
            if u.path == "/api/sets":
                return self.send(200, {**DOCK.sets(), "onStream": DOCK.on_stream_ids(), **DOCK.setups_view(),
                                       "setChars": DOCK.read_set_chars(), "uiVersion": ui_version()})
            if u.path == "/api/bracket":
                return self.send(200, {**DOCK.bracket(), "onStream": DOCK.on_stream_ids(), **DOCK.setups_view(),
                                       "setChars": DOCK.read_set_chars(), "uiVersion": ui_version()})
            if u.path == "/api/characters":
                return self.send(200, {"cast": DOCK.cast(), "players": DOCK.players_view()})
            if u.path == "/api/log":
                events = DOCK.with_video_times(DOCK.read_log())
                chars = DOCK.read_set_chars()
                for e in events:
                    e["text"], e["clock"] = describe(e, DOCK.chars_of(e, chars)), clock(e["t"])
                return self.send(200, {"events": events[-150:][::-1], "count": len(events), "logDir": DOCK.log_dir()})
            if u.path == "/api/changes":
                q = urllib.parse.parse_qs(u.query)
                since = (q.get("since") or [None])[0]
                version = DOCK.wait_change(int(since) if since not in (None, "") else None)
                return self.send(200, {"version": version})
        except ApiError as e:
            return self.send(502, {"error": str(e)})
        except Exception as e:  # keep the dock alive
            return self.send(500, {"error": f"{type(e).__name__}: {e}"})
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        u0 = urllib.parse.urlparse(self.path)
        if u0.path == "/login" and LAN.on and not LAN.is_local(self.client_address[0]):
            return self.do_login()
        if self.lan_gate(u0):
            return None
        if not self.api_guard():
            return None
        if self.role == "view":
            return self.send(403, {"error": "View-only access: this PIN can't change anything."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(min(n, 1_000_000)).decode("utf-8") or "{}")
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/onstream":
                return self.send(200, DOCK.put_on_stream(payload))
            if u.path == "/api/slot":
                return self.send(200, DOCK.slot_action(payload))
            if u.path == "/api/setup":
                if payload.get("action") == "clear":
                    return self.send(200, DOCK.clear_setup(payload))
                return self.send(200, DOCK.assign_setup(payload))
            if u.path == "/api/setups":
                DOCK.set_setups(payload)
                return self.send(200, {"ok": True, **DOCK.setups_view()})
            if u.path == "/api/chars":
                if not payload.get("setId"):
                    raise ValueError("no set")
                if not DOCK.save_chars(payload):
                    raise ValueError("Pick at least one character.")
                return self.send(200, {"ok": True})
            if u.path == "/api/action":
                result = DOCK.action(payload)
                return self.send(200, {"ok": True, "result": result, "queued": bool((result or {}).get("queued"))})
            if u.path == "/api/log/delete":
                DOCK.delete_event(payload.get("id"))
                return self.send(200, {"ok": True})
            if u.path == "/api/openfolder":
                folder = DOCK.log_dir()
                os.makedirs(folder, exist_ok=True)
                with LOCK:
                    DOCK.write_exports()
                if hasattr(os, "startfile"):
                    os.startfile(folder)
                return self.send(200, {"ok": True, "folder": folder})
            if u.path == "/api/streamids":
                for k in STREAMS:
                    if k in payload:
                        DOCK.config["streamIds"][k] = payload[k] or None
                save_json(CONFIG_FILE, DOCK.config)
                DOCK.bump()
                return self.send(200, {"ok": True})
            if u.path == "/api/tournament":
                if payload.get("eventId"):
                    DOCK.config["eventId"] = payload["eventId"]
                    save_json(CONFIG_FILE, DOCK.config)
                if "tournamentSlug" in payload:
                    slug = str(payload["tournamentSlug"]).strip().strip("/")
                    m = re.search(r"tournament/([a-z0-9-]+)", slug)  # accept a full URL too
                    DOCK.config["tournamentSlug"] = m.group(1) if m else slug
                    DOCK.config["pinSlug"] = bool(DOCK.config["tournamentSlug"]) and not payload.get("refreshLink")
                t = DOCK.load_tournament(refresh_link=bool(payload.get("refreshLink")))
                DOCK.bump()
                return self.send(200, {"ok": True, "tournament": t.get("name"), "slug": DOCK.config["tournamentSlug"]})
        except ApiError as e:
            return self.send(502, {"error": str(e)})
        except (ValueError, KeyError) as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:
            return self.send(500, {"error": f"{type(e).__name__}: {e}"})
        return self.send(404, {"error": "not found"})


def main():
    global DOCK
    DOCK = Dock()

    class Server(ThreadingHTTPServer):
        # On Windows, address reuse lets a second dock bind the same port silently (two docks
        # answering at random). Without it, a second start fails as intended.
        allow_reuse_address = False

    try:
        srv = Server((HOST, PORT), Handler)
    except OSError:
        print(f"Port {PORT} is busy: the Ultimate Dock is probably already running.")
        return
    if not os.path.isfile(CONFIG_FILE):  # first start: write the settings file so it can be edited
        save_json(CONFIG_FILE, DOCK.config)
    print(f"Super Stream Bros Ultimate dock running at http://127.0.0.1:{PORT}/")
    print(LAN.describe())
    print(f"Timestamps: {LOG_ROOT}")
    print(f"start.gg token ({TOKEN_VAR}):", "found" if get_token() else
          f"NOT SET (run set_token.bat{'' if TOKEN_VAR == 'STARTGG_TOKEN' else ' ' + TOKEN_VAR}, then restart this)")
    print("Leave this window open while recording. Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
