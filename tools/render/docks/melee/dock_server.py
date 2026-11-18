"""Super Stream Bros Melee dock: local server for the bracket + stream overlay pages.

Run:   start_dock.bat  (or: python dock_server.py)   then open_docks.bat, or in OBS:
       Docks > Custom Browser Docks, URL http://127.0.0.1:8765/  (and /bracket, /active)

- Talks to start.gg with the token in the STARTGG_TOKEN environment variable (set_token.bat).
  The token stays in this process; it is never sent to the page or written to disk.
- Writes the OBS overlay files to output\\ next to this file (same file names as Stream Updater).
- Your settings: dock_config.json (written on first start; see README.md):
    "shortLink"     your series' start.gg short link (follows it to the newest tournament)
    "themesFolder"  where the theme folders live (default: ..\\..\\overlays\\melee_themes, shared
                    with the VOD renderer; layout.json there also sizes the OBS name boxes)
- Listens on 127.0.0.1 only. Stdlib only.
"""

import collections
import base64
import csv
import io
import json
import os
import re
import shutil
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import socket

import lan as lanmod  # optional LAN access (lan.py next to this file)

# Try IPv4 before IPv6. On the stream laptop's network one of start.gg's IPv6 addresses
# intermittently doesn't answer (2026-10-21), and Python waits out the full timeout per
# address before falling back, so the docks stalled 20-40 s per request. Browsers fall back
# within milliseconds, which is why start.gg itself looked fine. IPv6 stays as a fallback.
_getaddrinfo = socket.getaddrinfo


def _ipv4_first(*args, **kwargs):
    return sorted(_getaddrinfo(*args, **kwargs), key=lambda r: r[0] != socket.AF_INET)


socket.getaddrinfo = _ipv4_first

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
ASSETS = os.path.join(HERE, "assets")
STOCKS = os.path.join(ASSETS, "stock_icons")
OUTPUT = os.path.join(HERE, "output")
CONFIG_FILE = os.path.join(HERE, "dock_config.json")
STATE_FILE = os.path.join(HERE, "dock_state.json")
PREFS_FILE = os.path.join(HERE, "player_prefs.json")
FONTS = os.path.join(ASSETS, "fonts")  # your stream font (.otf/.ttf): measures names for the OBS name boxes
# One folder per look (Default, Halloween, Christmas, specials...): theme.json + optional overlay.png.
# Found by find_themes_folder() below (dock_config.json "themesFolder", else the package's shared folder).
DEFAULT_SEASON = "Default"
# OBS name box (layout.json "name_box": [width, height] in 1920x1080 px); the dock shortens long names to fit it.
DEFAULT_NAME_BOX = [273, 59]

HOST, PORT = "127.0.0.1", int(os.environ.get("SSB_MELEE_DOCK_PORT") or 8765)
API_URL = "https://api.start.gg/gql/alpha"
MELEE_ID = 1  # start.gg videogame id for Super Smash Bros. Melee
UA = "SuperStreamBrosMeleeDock/1.0"

DEFAULT_CONFIG = {
    # Your series' start.gg short link (start.gg/<name> redirects to its newest tournament), e.g.
    # "https://www.start.gg/YourSeries". Empty: type a tournament slug in the dock's ⚙ instead.
    "shortLink": "",
    "themesFolder": "",    # empty = ..\..\overlays\melee_themes (package layout), else ..\Seasonal
    # Big events / LAN (see guides\06): read at start, restart the dock after changing them.
    "port": 8765,                  # the env var SSB_MELEE_DOCK_PORT wins if set
    "tokenVar": "STARTGG_TOKEN",   # user env var holding this instance's start.gg token
    "lan": False,                  # True = other devices on the network may use the pages (needs lanPin)
    "lanPin": "",                  # full control from other devices (6+ characters)
    "lanViewPin": "",              # optional: look-only access (bracket screens)
    "bracketCacheSeconds": 5,      # whole-bracket fetches are shared for this long (raise for big brackets)
    "maxBracketPages": 16,         # 25 sets per page: 16 = up to 400 sets
    "tournamentSlug": "",  # filled in automatically; set by hand to pin a tournament
    "eventId": None,
    "streamId": None,  # which start.gg stream "Put on stream" assigns (picked in the dock settings)
    "pollSeconds": 20,
    "season": DEFAULT_SEASON,  # theme folder name in the themes folder
    "seasonRounds": True,      # use the season's round names
    "seasonOverlay": True,     # use the season's overlay.png
    # Setup names in order (count = len). Kept week to week; set in ⚙. The first is always
    # "Main Setup" (same name as its replay drive folder) and is the default stream setup.
    "setups": ["Main Setup", "Setup 2"],
    "streamSetup": 0,          # index into setups that is on stream ("Put on stream" stamps it too)
}
MAIN_SETUP = "Main Setup"
SETUPS_MAX = 16
LOG_ROOT = os.path.join(HERE, "timestamps")      # timestamps\<slug>\ setups.jsonl / setups.csv / Setup times.txt
SETUP_STATE_FILE = os.path.join(HERE, "setup_state.json")  # which set is on which setup right now

LOCK = threading.Lock()
SETUP_LOCK = threading.RLock()
CACHE_LOCK = threading.Lock()    # guards the per-key fetch locks in Dock.cached
PENDING_LOCK = threading.Lock()  # actions queued while start.gg sets up the bracket


# ---------------------------------------------------------------- files

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))


def write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def transparent_png():
    def chunk(kind, body):
        c = struct.pack(">I", len(body)) + kind + body
        return c + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


BLANK_PNG = transparent_png()


def find_themes_folder():
    """The theme folders (Default\\, Halloween\\, ...): dock_config.json "themesFolder" (absolute, or
    relative to this folder), else the package's tools\\render\\overlays\\melee_themes (the VOD renderer
    reads the same one, so stream and VODs match), else a Seasonal\\ folder next to this dock's folder."""
    want = str(load_json(CONFIG_FILE, {}).get("themesFolder") or "").strip()
    cands = [os.path.join(HERE, os.path.expandvars(want))] if want else []  # join keeps an absolute path
    cands += [os.path.join(HERE, "..", "..", "overlays", "melee_themes"),
              os.path.join(os.path.dirname(HERE), "Seasonal")]
    for c in cands:
        if os.path.isdir(c):
            return os.path.normpath(c)
    if want:
        print(f"themesFolder {want!r} not found; no themes.")
    return os.path.normpath(cands[0])


SEASONAL = find_themes_folder()

# Settings needed before the dock starts (dock_config.json; defaults = this PC only, as before).
BOOT_CONFIG = load_json(CONFIG_FILE, {})
PORT = int(os.environ.get("SSB_MELEE_DOCK_PORT") or BOOT_CONFIG.get("port") or PORT)
TOKEN_VAR = str(BOOT_CONFIG.get("tokenVar") or "STARTGG_TOKEN").strip()
LAN = lanmod.Lan(BOOT_CONFIG, PORT, "Super Stream Bros Melee")
HOST = LAN.host
PRIVATE_KEYS = ("lanPin", "lanViewPin")  # never sent to the pages


def public_config(cfg):
    return {k: v for k, v in cfg.items() if k not in PRIVATE_KEYS}


def name_box():
    """[width, height] of the OBS name boxes, from layout.json in the themes folder."""
    try:
        with open(os.path.join(SEASONAL, "layout.json"), encoding="utf-8-sig") as f:  # Notepad may add a BOM
            box = json.load(f).get("name_box")
    except (OSError, ValueError, AttributeError):
        box = None
    try:
        w, h = (float(v) for v in box)
        return [w, h] if w > 0 and h > 0 else DEFAULT_NAME_BOX
    except (TypeError, ValueError):
        return DEFAULT_NAME_BOX


def stream_font():
    """Your stream font: the first .otf/.ttf in assets\\fonts\\ (None = the page uses a system font)."""
    try:
        names = sorted(n for n in os.listdir(FONTS) if n.lower().endswith((".otf", ".ttf")))
    except OSError:
        return None
    return names[0] if names else None


def clock(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


def day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def tag_of(slot):
    return (slot or {}).get("tag") or (slot or {}).get("name") or "?"


def result_text(s):
    """'A 3-1 B' (winner first) or 'DQ: B' for a finished set (simplified set)."""
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


def same_set(cur, set_id, identifier=None, entrants=()):
    """Is this the set on a setup? By id, or by set letter + both players: start.gg's
    "preview_..." ids (bracket not started yet) change once the bracket starts."""
    if not cur:
        return False
    if str(cur.get("setId")) == str(set_id):
        return True
    mine = {str(cur.get("e1")), str(cur.get("e2"))}
    return (bool(identifier) and identifier == cur.get("identifier") and "None" not in mine
            and mine == {str(e) for e in entrants})


# ---------------------------------------------------------------- seasonal themes

def list_seasons():
    """Theme folders in Seasonal\\ (each has theme.json; Default first)."""
    out = []
    try:
        names = os.listdir(SEASONAL)
    except OSError:
        return out
    for name in names:
        folder = os.path.join(SEASONAL, name)
        if not os.path.isfile(os.path.join(folder, "theme.json")):
            continue
        t = load_json(os.path.join(folder, "theme.json"), {})
        out.append({"id": name, "name": t.get("name") or name,
                    "hasOverlay": os.path.isfile(os.path.join(folder, "overlay.png")),
                    "hasRounds": bool(t.get("rounds"))})
    out.sort(key=lambda s: (s["id"] != DEFAULT_SEASON, s["name"].lower()))
    return out


def load_season(name):
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return {}
    return load_json(os.path.join(SEASONAL, name, "theme.json"), {})


def themed_round(theme, plain, losers_top8=False):
    """start.gg round name -> the theme's name. Unknown names pass through unchanged."""
    rounds = (theme or {}).get("rounds") or {}
    if not rounds or not plain:
        return plain
    if losers_top8 and rounds.get("Losers Top 8"):
        return rounds["Losers Top 8"]
    if plain in rounds:
        return rounds[plain]
    for key, value in rounds.items():
        if "{n}" in key:
            m = re.fullmatch(re.escape(key).replace(re.escape("{n}"), r"(\d+)"), plain)
            if m:
                return value.replace("{n}", m.group(1))
    return plain


# start.gg's own round names; a round typed (or left over) in this form gets the theme's name too.
STARTGG_ROUND = re.compile(r"(Winners|Losers) (Round \d+|Quarter-Final|Semi-Final|Final)|Grand Final( Reset)?|Round \d+")

WINNERS_TOP = {8: {"Winners Semi-Final", "Winners Final", "Grand Final", "Grand Final Reset"},
               4: {"Winners Final", "Grand Final", "Grand Final Reset"}}
LOSERS_TOP = {8: {"Losers Quarter-Final", "Losers Semi-Final", "Losers Final"},
              4: {"Losers Semi-Final", "Losers Final"}}


def top_info(plain, round_num, bracket_type, round_numbers):
    """({8: in top 8, 4: in top 4}, is the losers top-8 round). Losers Final is the lowest
    (most negative) round number; the losers round with 4 players left is 3 rounds before it."""
    losers = [n for n in round_numbers if n < 0]
    if bracket_type == "DOUBLE_ELIMINATION" and round_num is not None and round_num < 0 and losers:
        back = round_num - min(losers)  # 0 = Losers Final, 1 = Losers Semi-Final, ...
        return {8: back <= 3, 4: back <= 1}, back == 3
    return {n: plain in WINNERS_TOP[n] or plain in LOSERS_TOP[n] for n in (8, 4)}, False


# ---------------------------------------------------------------- token / start.gg

def get_token():
    # TOKEN_VAR: "tokenVar" in dock_config.json (default STARTGG_TOKEN). Several docks on one hub each
    # get their own token (start.gg's rate limit is per token).
    tok = os.environ.get(TOKEN_VAR, "").strip()
    if tok:
        return tok
    # Fallback: a user env var set after this process (or OBS) started.
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


NET_HELP = "No internet connection to start.gg (check Wi-Fi). The overlay still works by hand."


def open_with_retry(req, opener=None, tries=3):
    """Open a request, retrying short network drops (DNS failures, timeouts).
    HTTPError is passed through to the caller."""
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
        raise ApiError("STARTGG_TOKEN is not set. Set it as a user environment variable, then restart the dock.")
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
    except urllib.error.HTTPError as e:  # the redirect we want arrives as a 3xx "error"
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
  phaseGroup { id bracketType rounds { number } }
  slots {
    entrant { id name initialSeedNum participants { id gamerTag prefix } }
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

# Whole bracket (every state, empty future sets too) for the bracket overview page.
# start.gg refuses a request that returns more than 1000 objects ("query complexity"). A set costs
# about 28 with these fields (measured 2026-11-11 on PROTOCOL #58: 25 sets = 701, 30 = 811, 40 = refused),
# so: 25 per page here, 30 for the open list. Re-measure (extensions.queryComplexity) after adding fields.
Q_BRACKET = """
query B($eventId: ID!, $page: Int!) {
  event(id: $eventId) {
    sets(page: $page, perPage: 25, sortType: ROUND, filters: { hideEmpty: false }) {
      pageInfo { totalPages }
      nodes {
        id identifier fullRoundText round state winnerId startedAt completedAt
        stream { id streamName }
        station { id number }
        phaseGroup { id displayIdentifier bracketType rounds { number } phase { id name phaseOrder } }
        slots {
          prereqType prereqId prereqPlacement
          entrant { id name initialSeedNum participants { id gamerTag prefix } }
          seed { seedNum entrant { id } }
          standing { stats { score { value } } }
        }
      }
    }
  }
}"""

Q_ENTRANTS = """
query E($eventId: ID!, $page: Int!) {
  event(id: $eventId) {
    entrants(query: { page: $page, perPage: 80 }) {
      pageInfo { totalPages }
      nodes { id name participants { id gamerTag prefix user { name images { type url } } } }
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


def simplify_set(s, theme=None):
    """theme: the active season's theme.json (round names), or None for start.gg's names."""
    slots = []
    for sl in s.get("slots") or []:
        ent = sl.get("entrant") or {}
        parts = ent.get("participants") or []
        p = parts[0] if parts else {}
        score = (((sl.get("standing") or {}).get("stats") or {}).get("score") or {}).get("value")
        slots.append({
            "entrantId": ent.get("id"),
            "name": ent.get("name") or "",
            "tag": p.get("gamerTag") or ent.get("name") or "",
            "prefix": p.get("prefix") or "",
            "score": score,
            # initialSeedNum is often empty; the phase seed is on the slot (first-round sets only,
            # Dock.fill_seeds copies it to the player's later sets).
            "seed": ent.get("initialSeedNum") or (
                (sl.get("seed") or {}).get("seedNum")
                if str(((sl.get("seed") or {}).get("entrant") or {}).get("id")) == str(ent.get("id")) else None),
            # For empty slots: where the player will come from (another set's winner/loser, or a seed).
            "prereqType": sl.get("prereqType"),
            "prereqId": sl.get("prereqId"),
            "prereqPlacement": sl.get("prereqPlacement"),
        })
    pg = s.get("phaseGroup") or {}
    plain = s.get("fullRoundText") or ""
    top, losers_top8 = top_info(plain, s.get("round"), pg.get("bracketType"),
                                [r.get("number") for r in pg.get("rounds") or [] if r.get("number") is not None])
    return {
        "group": pg.get("displayIdentifier"),
        "groupId": pg.get("id"),
        "bracketType": pg.get("bracketType"),
        "phase": (pg.get("phase") or {}).get("name"),
        "phaseOrder": (pg.get("phase") or {}).get("phaseOrder"),
        "id": s.get("id"),
        "identifier": s.get("identifier"),
        "round": themed_round(theme, plain, losers_top8),  # what the docks and the overlay show
        "roundPlain": plain,                                 # start.gg's own name
        "top8": top[8],
        "top4": top[4],
        "losersTop8": losers_top8,
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


# ---------------------------------------------------------------- app state

class Dock:
    def __init__(self):
        self.config = {**DEFAULT_CONFIG, **load_json(CONFIG_FILE, {})}
        if not self.config.get("setups"):
            self.config["setups"] = list(DEFAULT_CONFIG["setups"])
            self.config["streamSetup"] = DEFAULT_CONFIG["streamSetup"]
        self.config["setups"][0] = MAIN_SETUP
        self.state = load_json(STATE_FILE, {})
        self.prefs = load_json(PREFS_FILE, {})
        self.tournament = None
        self.entrants = {}  # entrantId -> {name, images}
        self.img_cache = {}
        self.cache = {}  # short-lived start.gg results, so two docks don't double the API calls
        self.version = 0  # bumped on every change; docks long-poll /api/changes to stay in sync
        self.reported = {}  # setId -> result reported in the dock, until start.gg's lists show it
        self.changed = threading.Condition()
        os.makedirs(OUTPUT, exist_ok=True)
        if not self.state:
            self.state = blank_overlay()
            self.write_overlay(self.state)
        self.apply_overlay_image()
        if self.theme_round(self.state):  # e.g. a round left on the overlay from before a theme was picked
            self.write_overlay(self.state)
            save_json(STATE_FILE, self.state)
        # Which set is on each setup right now: {"0": {setId, identifier, round, p1, p2, e1, e2, since}}
        self.on_setup = load_json(SETUP_STATE_FILE, {}).get("onSetup") or {}

    # -- setups (names in ⚙; "Put on setup" time-stamps sets so replays can be matched later)
    def setup_names(self):
        return [str(n) for n in self.config.get("setups") or []]

    def setup_label(self, idx):
        names = self.setup_names()
        return names[idx] if 0 <= idx < len(names) else f"Setup {idx + 1}"

    def save_setup_state(self):
        save_json(SETUP_STATE_FILE, {"onSetup": self.on_setup})

    def log_dir(self):
        slug = re.sub(r"[^a-z0-9-]", "", (self.config.get("tournamentSlug") or "").lower())
        return os.path.join(LOG_ROOT, slug or "no-tournament")

    def read_log(self):
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
        out.sort(key=lambda e: e.get("t") or 0)  # stable: same-second events keep file order
        return out

    def add_event(self, kind, idx, info=None, t=None, **extra):
        ev = {"id": str(time.time_ns()), "t": round(t or time.time(), 3), "setup": idx + 1,
              "setupName": self.setup_label(idx), "event": kind}
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
        for seg, s in self.segments(self.read_log()).items():
            sid = str((s["end"] or {}).get("setId") or "")
            if sid and not sid.startswith("preview_") and isinstance(s["setup"], int):
                out[sid] = {"seg": seg, "setup": s["setup"] - 1, "end": s["end"]}
        self.__dict__["past_cache"] = (key, out)
        return out

    def write_setup_exports(self):
        """setups.csv (every event) and 'Setup times.txt' (one block per setup, start - end)."""
        folder = self.log_dir()
        events = self.read_log()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "clock_time", "setup", "setup_name", "event", "round", "set", "player1", "player2",
                    "result", "reason", "note", "set_id", "startgg_started", "unix_time"])
        for e in events:
            st = e.get("startedAt")
            w.writerow([day(e["t"]), clock(e["t"]), e.get("setup", ""), e.get("setupName", ""), e.get("event", ""),
                        e.get("round", ""), e.get("identifier", ""), e.get("p1", ""), e.get("p2", ""),
                        e.get("result", ""), e.get("reason", ""), e.get("note", ""), e.get("setId", ""),
                        clock(st) if st else "", e["t"]])
        write_atomic(os.path.join(folder, "setups.csv"), buf.getvalue().encode("utf-8-sig"))  # BOM: Excel
        name = (self.tournament or {}).get("name") or self.config.get("tournamentSlug") or "Tournament"
        lines = [f"{name} · sets per setup (laptop clock)", ""]
        # Each start carries "seg" (its own id) and its end repeats it, so a start logged late
        # (setup picked at report, backdated to start.gg's start time) still pairs up.
        # One line per segment, with corrections applied (last result, corrected setup).
        segs = list(self.segments(events).values())
        for num in sorted({s["setup"] for s in segs if s["setup"]}):
            mine = [s for s in segs if s["setup"] == num]
            lines += [f"== {mine[-1].get('setupName') or f'Setup {num}'} =="]
            for s in mine:
                start, end = s["start"], s["end"]
                ident = f" ({start['identifier']})" if start.get("identifier") else ""
                fixed = start.get("setup") != num
                lines.append(f"  {clock(start['t'])} - {clock(end['t']) if end else '(playing)'}  "
                             f"{start.get('round') or 'Set'}{ident}: {start.get('p1', '?')} vs {start.get('p2', '?')}"
                             f"{'  ->  ' + (end.get('result') or end.get('reason') or '') if end else ''}"
                             f"{'  [setup picked at report]' if start.get('note') else ''}"
                             f"{'  [setup corrected, was ' + str(start.get('setupName')) + ']' if fixed else ''}")
            lines.append("")
        write_atomic(os.path.join(folder, "Setup times.txt"), ("\r\n".join(lines) + "\r\n").encode("utf-8-sig"))

    def end_setup(self, idx, reason, t=None, result=""):
        cur = self.on_setup.pop(str(idx), None)
        if not cur:
            return None
        return self.add_event("set_end", idx, cur, t=t, reason=reason, result=result)

    def setup_of(self, set_id, identifier=None, entrants=()):
        for k, cur in self.on_setup.items():
            if same_set(cur, set_id, identifier, entrants):
                return int(k)
        return None

    @staticmethod
    def set_info(p):
        return {"setId": str(p["setId"]), "identifier": str(p.get("identifier") or "")[:12],
                "round": str(p.get("round") or "")[:80], "p1": str(p.get("p1") or "?")[:80],
                "p2": str(p.get("p2") or "?")[:80], "e1": p.get("e1"), "e2": p.get("e2"),
                "startedAt": p.get("startedAt") if isinstance(p.get("startedAt"), (int, float)) else None}

    def assign_setup(self, p):
        """Put a set on a setup: log it (time-stamped), end whatever was there, then mark the
        set in progress on start.gg (after the timestamp is safely written)."""
        try:
            idx = int(p.get("setup"))
        except (TypeError, ValueError):
            raise ValueError("bad setup") from None
        if not (0 <= idx < len(self.setup_names())) or not p.get("setId"):
            raise ValueError("bad setup or set")
        info = self.set_info(p)
        with SETUP_LOCK:
            ents = [info["e1"], info["e2"]]
            if same_set(self.on_setup.get(str(idx)), info["setId"], info["identifier"], ents):
                return {"ok": True, "already": True}
            now = time.time()
            if self.on_setup.get(str(idx)):
                self.end_setup(idx, f"next set on {self.setup_label(idx)}", now)
            other = self.setup_of(info["setId"], info["identifier"], ents)
            if other is not None:
                self.end_setup(other, f"moved to {self.setup_label(idx)}", now)
            ev = self.add_event("on_setup", idx, info, t=now)
            self.on_setup[str(idx)] = {**info, "since": now, "seg": ev["id"]}
            self.save_setup_state()
        self.bump(drop_cache=False)
        warning, queued = "", False
        if p.get("state") != 2 and not p.get("noStart"):
            try:
                if info["setId"].startswith("preview_") and self.bracket_starting():
                    self.queue_action("start", info["setId"])  # old id is dead; send it once start.gg is back
                    queued = True
                else:
                    gql(MUTATIONS["start"], {"setId": info["setId"]})
                    self.mark_started(info["setId"])
                    self.bump()
            except ApiError as e:
                warning = str(e)
        return {"ok": True, "clock": clock(ev["t"]), "warning": warning, "queued": queued}

    def mark_started(self, set_id):
        """The dock started this set on start.gg. Starting a preview set starts the whole bracket."""
        self.__dict__.setdefault("started", {})[str(set_id)] = time.time()
        if str(set_id).startswith("preview_"):
            self.__dict__["starting_since"] = time.time()

    def clear_setup(self, p):
        try:
            idx = int(p.get("setup"))
        except (TypeError, ValueError):
            raise ValueError("bad setup") from None
        with SETUP_LOCK:
            ev = self.end_setup(idx, "cleared by hand")
            self.save_setup_state()
        if not ev:
            raise ValueError(f"Nothing is on {self.setup_label(idx)}.")
        self.bump(drop_cache=False)
        return {"ok": True, "clock": clock(ev["t"])}

    def set_setups(self, payload):
        names = [str(n).strip()[:40] for n in (payload.get("names") or [])][:SETUPS_MAX]
        names = [MAIN_SETUP] + [n or f"Setup {i + 2}" for i, n in enumerate(names[1:])]  # Main Setup always first
        stream = payload.get("streamSetup")
        stream = int(stream) if isinstance(stream, int) or (isinstance(stream, str) and stream.isdigit()) else None
        with SETUP_LOCK:
            for k in list(self.on_setup):
                if int(k) >= len(names):
                    self.end_setup(int(k), "setup removed in settings")
            self.config["setups"] = names
            self.config["streamSetup"] = stream if stream is not None and stream < len(names) else None
            save_json(CONFIG_FILE, self.config)
            self.save_setup_state()
        self.bump(drop_cache=False)

    def after_report(self, p, winner_tag="", result=""):
        """A set was reported in the dock: end its setup segment. If it was never put on a setup,
        log the setup picked in the report dialog (start = start.gg's startedAt when known)."""
        info = self.set_info({**p, "setId": p.get("setId")})
        ents = [info["e1"], info["e2"]]
        now = time.time()
        with SETUP_LOCK:
            idx = self.setup_of(info["setId"], info["identifier"], ents)
            pick = None
            if p.get("setup") not in (None, ""):
                try:
                    pick = int(p["setup"])
                except (TypeError, ValueError):
                    pick = None
                if pick is not None and not 0 <= pick < len(self.setup_names()):
                    pick = None
            past = self.past_segments().get(info["setId"]) if idx is None else None
            if past:
                # Reported before (result was reset): keep the segment and its times. Only the
                # result changes, and the setup if another one is picked this time.
                new = pick if pick is not None else past["setup"]
                if not 0 <= new < len(self.setup_names()):
                    return
                seg_info = {**info, "seg": past["seg"]}
                if new != past["setup"]:
                    self.add_event("setup_fix", new, seg_info, t=now,
                                   note=f"setup corrected at re-report (was {past['end'].get('setupName')})")
                self.add_event("set_end", new, seg_info, t=past["end"].get("t") or now, reason="re-reported in dock",
                               result=result, note=f"result corrected at {clock(now)}; end time kept from the first report")
                return
            if idx is None and pick is not None:
                idx = pick
                st = info.get("startedAt")
                t = st if st and st < now else now
                ev = self.add_event("on_setup", idx, info, t=t,
                                    note="setup picked at report" + ("; start = start.gg start time" if t != now else "; start unknown"))
                self.on_setup[str(idx)] = {**info, "since": t, "seg": ev["id"]}
            if idx is not None:
                self.end_setup(idx, "reported in dock", now, result)
                self.save_setup_state()

    def check_finished(self, sets, full=False, rebuilding=False):
        """Follow the sets on setups: pick up a new set id, end a set that is now done on
        start.gg (reported anywhere, e.g. on start.gg itself), and end sets the bracket no longer
        has because it was restarted on start.gg (e.g. reseeded for a late arrival): those start
        fresh, with a new log entry when they are put on a setup again.
        full: sets is the whole bracket (a set missing from it is really gone).
        Returns True if a set on a setup wasn't found (caller with a partial list: check the full one)."""
        changed, unresolved = False, False
        if not sets or rebuilding:  # start.gg blank / held list: nothing can be judged
            return False
        with SETUP_LOCK:
            for k, cur in list(self.on_setup.items()):
                was_preview = str(cur["setId"]).startswith("preview_")
                mine = {str(cur.get("e1")), str(cur.get("e2"))}
                s = next((x for x in sets if str(x["id"]) == str(cur["setId"])), None)
                gone = False
                if s:
                    # Same id but other players: a preview id reused after a restart + reseed.
                    theirs = {str(sl.get("entrantId")) for sl in s["slots"]}
                    gone = "None" not in mine and "None" not in theirs and len(theirs) == 2 and theirs != mine
                else:
                    s = next((x for x in sets if same_set(cur, x["id"], x.get("identifier"),
                                                          [sl.get("entrantId") for sl in x["slots"]])), None)
                    if s and not was_preview:
                        gone = True  # a numeric id never changes: same pairing, new id = restarted bracket
                    elif s:
                        cur["setId"] = str(s["id"])  # bracket started: preview id -> real id
                        changed = True
                    elif full:
                        # Not in the bracket any more. Wait 45 s before believing it: right after a
                        # bracket start, start.gg's list can be incomplete for a moment.
                        gone = time.time() - cur.setdefault("missingSince", time.time()) > 45
                    else:
                        unresolved = True
                if s:
                    cur.pop("missingSince", None)
                if gone:
                    self.__dict__.pop("hidden_sets", None)  # bye structure may differ after a reseed
                    self.end_setup(int(k), "bracket restarted")
                    changed = True
                    continue
                if not s:
                    continue
                if s.get("state") == 3:
                    t = s.get("completedAt") or time.time()
                    t = min(max(t, cur.get("since") or t), time.time())
                    self.end_setup(int(k), "reported", t, result_text(s))
                    changed = True
            if changed:
                self.save_setup_state()
        if changed:
            self.bump(drop_cache=False)
        return unresolved

    def setups_view(self):
        return {"setups": [{"index": i, "name": n, "on": self.on_setup.get(str(i))}
                           for i, n in enumerate(self.setup_names())],
                "streamSetup": self.config.get("streamSetup"),
                # setId -> setup index a finished set was logged on (pre-picked when it is re-reported)
                "past": {sid: s["setup"] for sid, s in self.past_segments().items()}}

    # -- seasonal theme
    def theme_round(self, st, before=None):
        """Give the overlay's round the active theme's name. Returns True if it changed.
        - a start.gg-style name ("Winners Semi-Final", typed or left over) is start.gg's name
        - a themed name of the recorded roundPlain (now, or `before` a theme switch) follows the theme
        - anything else was typed by hand and is left alone"""
        rnd = st.get("round") or ""
        if STARTGG_ROUND.fullmatch(rnd):
            if rnd != st.get("roundPlain"):
                st["roundPlain"], st["losersTop8"] = rnd, False
        elif not st.get("roundPlain") or rnd not in {before, self.display_round(st["roundPlain"], st.get("losersTop8"))}:
            return False
        new = self.display_round(st["roundPlain"], st.get("losersTop8"))
        if new != rnd:
            st["round"] = new
            return True
        return False

    def season(self):
        return load_season(self.config.get("season") or DEFAULT_SEASON)

    def round_theme(self):
        """Theme used for round names, or None (Default season, or round names switched off)."""
        return self.season() if self.config.get("seasonRounds", True) else None

    def display_round(self, plain, losers_top8=False):
        return themed_round(self.round_theme(), plain, losers_top8)

    def apply_overlay_image(self):
        """Copy the active season's overlay.png (else Default's) to output\\overlay.png, which OBS shows."""
        season = self.config.get("season") or DEFAULT_SEASON
        src = os.path.join(SEASONAL, season, "overlay.png")
        if not (self.config.get("seasonOverlay", True) and load_season(season) and os.path.isfile(src)):
            src = os.path.join(SEASONAL, DEFAULT_SEASON, "overlay.png")
        if not os.path.isfile(src):
            print(f"No overlay image found ({src}); output\\overlay.png left as is.")
            return
        dest = os.path.join(OUTPUT, "overlay.png")
        try:
            # Cheap check first: same file, same modified time -> nothing to do (runs on every poll,
            # so a theme overlay saved from paint.net reaches OBS without restarting the dock).
            sig = (src, os.path.getmtime(src), os.path.getsize(src))
            if sig == getattr(self, "_overlay_sig", None) and os.path.isfile(dest):
                return
            self._overlay_sig = sig
            with open(src, "rb") as f:
                data = f.read()
            if os.path.isfile(dest) and os.path.getsize(dest) == len(data):
                with open(dest, "rb") as f:
                    if f.read() == data:
                        return
            write_atomic(dest, data)
        except OSError as e:
            print(f"Could not update overlay image: {e}")

    def set_season(self, payload):
        """Switch theme / round names / overlay graphic. The round on stream follows the switch
        unless it was typed by hand."""
        st = self.state
        before = self.display_round(st.get("roundPlain") or "", st.get("losersTop8"))
        name = str(payload.get("season") or DEFAULT_SEASON)
        if name not in [s["id"] for s in list_seasons()]:
            raise ValueError(f"unknown theme '{name}'")
        self.config["season"] = name
        for key in ("seasonRounds", "seasonOverlay"):
            if key in payload:
                self.config[key] = bool(payload[key])
        save_json(CONFIG_FILE, self.config)
        self.apply_overlay_image()
        with LOCK:
            if self.theme_round(st, before):
                self.write_overlay(st)
                save_json(STATE_FILE, st)
        self.bump()  # cached sets carry round names: refetch

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
        # The overlay's set (put on stream during the blackout) gets its new id too.
        ov = self.state.get("setId")
        if ov and str(ov).startswith("preview_") and not any(str(s.get("id")) == str(ov) for s in sets):
            pair = sorted(str((self.state.get(f"p{n}") or {}).get("entrantId")) for n in (1, 2))
            hit = next((s for s in sets if s.get("state") != 3 and
                        sorted(str(x.get("entrantId")) for x in s.get("slots") or []) == pair), None)
            if hit:
                self.state["setId"] = hit["id"]
                save_json(STATE_FILE, self.state)
                sent = True
        if sent:
            self.bump()
            self.bump_later()

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
            if self.__dict__.get("pending") or str(self.state.get("setId") or "").startswith("preview_"):
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

    # -- tournament
    def load_tournament(self, refresh_link=False):
        slug = self.config.get("tournamentSlug")
        if refresh_link or not slug:
            link = str(self.config.get("shortLink") or "").strip()
            if not link:
                raise ApiError("No tournament yet: type its slug in ⚙ and click Load slug, or put your series' "
                               "start.gg short link in dock_config.json (\"shortLink\") for Use latest.")
            slug = resolve_short_link(link)
        t = gql(Q_TOURNAMENT, {"slug": slug}).get("tournament")
        if not t:
            raise ApiError(f"Tournament '{slug}' not found.")
        if slug != self.config.get("tournamentSlug"):
            self.config["eventId"] = None
            self.entrants = {}
            with SETUP_LOCK:  # last tournament's setups are done; its log stays in its own folder
                self.on_setup = {}
                self.save_setup_state()
        self.config["tournamentSlug"] = slug
        # Protocol always runs Melee + Ultimate; the dock only ever uses Melee events.
        melee = [e for e in t.get("events") or [] if (e.get("videogame") or {}).get("id") == MELEE_ID]
        if not melee:
            raise ApiError(f"'{slug}' has no Melee event.")
        # Prefer singles, then the biggest event.
        melee.sort(key=lambda e: ("doubles" not in (e.get("name") or "").lower(), e.get("numEntrants") or 0),
                   reverse=True)
        t["events"] = melee
        if str(self.config.get("eventId")) not in [str(e["id"]) for e in melee]:
            self.config["eventId"] = melee[0]["id"]
        save_json(CONFIG_FILE, self.config)
        self.tournament = t
        return t

    def load_entrants(self):
        eid = self.config.get("eventId")
        if not eid:
            return
        out, page = {}, 1
        while True:
            ev = gql(Q_ENTRANTS, {"eventId": eid, "page": page}).get("event") or {}
            ents = ev.get("entrants") or {}
            for n in ents.get("nodes") or []:
                p = (n.get("participants") or [{}])[0]
                user = p.get("user") or {}
                img = next((i["url"] for i in user.get("images") or [] if i.get("type") == "profile"), "")
                out[str(n["id"])] = {
                    "entrantId": n["id"],
                    "tag": p.get("gamerTag") or n.get("name"),
                    "prefix": p.get("prefix") or "",
                    "name": user.get("name") or p.get("gamerTag") or n.get("name"),
                    "imageUrl": img,
                }
            if page >= ((ents.get("pageInfo") or {}).get("totalPages") or 1):
                break
            page += 1
        self.entrants = out

    def _event_id(self):
        if not self.tournament:
            self.load_tournament()
        eid = self.config.get("eventId")
        if not eid:
            raise ApiError("No event found in this tournament.")
        if not self.entrants:
            self.load_entrants()
        return eid

    def _header(self, eid):
        return {
            "tournament": {k: self.tournament.get(k) for k in ("name", "slug", "state")},
            "events": [{"id": e["id"], "name": e["name"], "numEntrants": e.get("numEntrants")} for e in self.tournament.get("events") or []],
            "eventId": eid,
            "streams": self.tournament.get("streams") or [],
            "streamId": self.config.get("streamId"),
            "fetchedAt": time.time(),
        }

    def sets(self):
        """Open sets + recent results for Home, built from the same whole-bracket data the bracket
        pages use. start.gg's lists filtered by state (the old source) trail the bracket by several
        seconds after an action, so Home used to lag behind the other pages; it also cost two
        extra requests per refresh. Now all pages share one fetch and always agree."""
        self.apply_overlay_image()  # picks up an edited theme overlay.png
        b = self.bracket()  # cached, held while start.gg is blank, seeds, setups; follows sets on setups
        sets = b["sets"]
        ready = lambda s: len(s["slots"]) == 2 and all(x["entrantId"] for x in s["slots"])
        order = lambda s: (abs(s.get("roundNum") or 0), len(s.get("identifier") or ""), s.get("identifier") or "")
        open_list = sorted((s for s in sets if s.get("state") != 3 and ready(s)), key=order)
        done = sorted((s for s in sets if s.get("state") == 3), key=lambda s: s.get("completedAt") or 0, reverse=True)[:15]
        out = {k: v for k, v in b.items() if k not in ("sets", "finalsLabel", "finalsFrom")}
        return {**out, "open": open_list, "done": done}

    def bracket(self):
        """Every set in the Melee event, for the bracket overview page."""
        eid = self._event_id()

        def fetch():
            out, page = [], 1
            theme = self.round_theme()
            while True:
                ev = gql(Q_BRACKET, {"eventId": eid, "page": page}).get("event") or {}
                sets = ev.get("sets") or {}
                out += [simplify_set(s, theme) for s in sets.get("nodes") or []]
                total = (sets.get("pageInfo") or {}).get("totalPages") or 1
                if page >= total or page >= max_pages:
                    if total > max_pages and not getattr(self, "_warned_pages", False):
                        self._warned_pages = True
                        print(f"Bracket has {total} pages of 25 sets; only {max_pages} are read. "
                              f'Raise "maxBracketPages" in dock_config.json (see guides\\06).')
                    break
                page += 1
            self.resolve_byes(out)
            # Label for the last rounds in the bracket overview (e.g. "Final Haunt"), from top 4 or top 8.
            return {**self._header(eid), "sets": out, "finalsLabel": (theme or {}).get("finalsLabel") or "",
                    "finalsFrom": 8 if (theme or {}).get("finalsFrom") == 8 else 4}
        # Every page counts against start.gg's limit: with many devices open, a longer shared cache
        # keeps a big bracket under it (see guides\06 for the numbers).
        max_pages = max(1, int(self.config.get("maxBracketPages") or 16))
        ttl = max(5, float(self.config.get("bracketCacheSeconds") or 5))
        data = self.cached(("bracket", eid), ttl, fetch)
        data = self.hold_last(("bracket", eid), data, data["sets"])
        self.fill_seeds(eid, data["sets"])
        if self.reported:
            data = {**data, "sets": self.patch_reported(data["sets"])}
        self.check_finished(data["sets"], full=True, rebuilding=bool(data.get("rebuilding")))
        return {**data, **self.setups_view()}

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
        """start.gg leaves "X vs bye" sets out of the list, so an empty slot can point at a set
        we don't have ("winner of hidden set" = whoever got the bye). Look those sets up (cached;
        they're structural) and follow them to the visible source, e.g. "Loser of B"."""
        visible = {str(s["id"]) for s in sets}
        cache = self.__dict__.setdefault("hidden_sets", {})
        for _ in range(4):  # chains are short (a bye set can feed another bye set)
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

    def entrant_info(self, entrant_id):
        return self.entrants.get(str(entrant_id))

    # -- overlay
    def write_overlay(self, st):
        files = {
            "match_round.txt": st.get("round", ""),
            "game_count.txt": st.get("gameCount", ""),
        }
        for i in (1, 2):
            p = st.get(f"p{i}") or {}
            files.update({
                f"player{i}_name.txt": p.get("name", ""),
                # "shown" = display fitted to the name plate by the dock page (prefix dropped / "…")
                f"player{i}_tag.txt": p.get("shown") or p.get("display", ""),
                f"player{i}_score.txt": str(p.get("score", 0)),
                f"player{i}_game_count.txt": str(p.get("score", 0)),
                f"player{i}_image_url.txt": p.get("imageUrl", ""),
                f"player{i}_character.txt": p.get("character", ""),
                f"player{i}_color.txt": p.get("color", ""),
            })
        for name, text in files.items():
            write_atomic(os.path.join(OUTPUT, name), str(text).encode("utf-8"))
        for i in (1, 2):
            p = st.get(f"p{i}") or {}
            src = os.path.join(STOCKS, f"{p.get('color') or 'neutral'} {p.get('character')}.png")
            dest = os.path.join(OUTPUT, f"player{i}_stock.png")
            if p.get("character") and os.path.isfile(src):
                with open(src, "rb") as f:
                    write_atomic(dest, f.read())
            else:
                write_atomic(dest, BLANK_PNG)

    def write_pfp(self, i, data_url):
        if not data_url:
            return
        m = re.match(r"data:image/png;base64,(.+)$", data_url, re.S)
        if not m:
            raise ValueError("pfp must be a PNG data URL")
        raw = base64.b64decode(m.group(1))
        if not raw.startswith(b"\x89PNG"):
            raise ValueError("pfp is not a PNG")
        write_atomic(os.path.join(OUTPUT, f"player{i}_pfp.png"), raw)

    def set_overlay(self, payload):
        st = blank_overlay()
        st["round"] = str(payload.get("round", ""))[:120]
        # start.gg's own round name, so a theme switch can re-label the round already on stream
        st["roundPlain"] = str(payload.get("roundPlain") or "")[:120]
        st["losersTop8"] = bool(payload.get("losersTop8"))
        self.theme_round(st)  # "Winners Final" typed in the round box becomes the theme's name
        st["gameCount"] = str(payload.get("gameCount", ""))[:40]
        st["setId"] = payload.get("setId")
        for i in (1, 2):
            p = payload.get(f"p{i}") or {}
            st[f"p{i}"] = {
                "entrantId": p.get("entrantId"),
                "tag": str(p.get("tag", ""))[:80],
                "prefix": str(p.get("prefix", ""))[:40],
                "display": str(p.get("display", ""))[:120],
                "shown": str(p.get("shown", ""))[:120],
                "name": str(p.get("name", ""))[:120],
                "score": max(0, min(9, int(p.get("score") or 0))),
                "imageUrl": str(p.get("imageUrl", ""))[:500],
                "character": str(p.get("character", ""))[:40],
                "color": str(p.get("color", "neutral"))[:20],
            }
            tag = st[f"p{i}"]["tag"]
            if tag and st[f"p{i}"]["character"]:
                self.prefs[tag] = {"character": st[f"p{i}"]["character"], "color": st[f"p{i}"]["color"]}
        with LOCK:
            self.write_overlay(st)
            for i in (1, 2):
                self.write_pfp(i, (payload.get(f"p{i}") or {}).get("pfp"))
            self.state = st
            save_json(STATE_FILE, st)
            save_json(PREFS_FILE, self.prefs)
        self.bump(drop_cache=False)  # nothing changed on start.gg
        return st

    # -- start.gg actions
    def action(self, payload):
        kind = payload.get("action")
        set_id = payload.get("setId")
        if kind not in MUTATIONS or not set_id:
            raise ValueError("unknown action")
        v = {"setId": set_id}
        if kind == "stream":
            v["streamId"] = payload.get("streamId")
            if not v["streamId"]:
                raise ApiError("This tournament has no stream set up on start.gg (Admin > Stream Queue).")
        if kind == "report":
            e1, e2 = payload.get("entrant1"), payload.get("entrant2")
            s1, s2 = int(payload.get("score1") or 0), int(payload.get("score2") or 0)
            if payload.get("dqLoser"):
                loser = payload["dqLoser"]
                if loser not in (e1, e2):
                    raise ValueError("bad DQ entrant")
                v.update(winnerId=e2 if loser == e1 else e1, isDQ=True)
            else:
                if s1 == s2:
                    raise ValueError("Scores are tied; a set needs a winner.")
                winner = e1 if s1 > s2 else e2
                games, n = [], 1
                # Order is unknown; record loser's games first, then the winner's.
                lose_id, lose_n = (e2, s2) if winner == e1 else (e1, s1)
                for _ in range(lose_n):
                    games.append({"winnerId": lose_id, "gameNum": n}); n += 1
                for _ in range(max(s1, s2)):
                    games.append({"winnerId": winner, "gameNum": n}); n += 1
                v.update(winnerId=winner, isDQ=False, gameData=games)
        if str(set_id).startswith("preview_") and self.bracket_starting():
            if kind in ("start", "call", "stream"):
                self.queue_action(kind, set_id, v)
                return {"queued": True}
            raise ApiError("start.gg is still setting up the bracket. Try again in a minute.")
        result = gql(MUTATIONS[kind], v)
        if kind == "report":
            t1, t2 = str(payload.get("p1") or "?"), str(payload.get("p2") or "?")
            if payload.get("dqLoser"):
                text = f"DQ: {t1 if payload['dqLoser'] == payload.get('entrant1') else t2}"
            else:
                text = f"{t1} {s1}-{s2} {t2}" if s1 > s2 else f"{t2} {s2}-{s1} {t1}"
            try:
                self.after_report({**payload, "e1": payload.get("entrant1"), "e2": payload.get("entrant2")},
                                  result=text)
            except Exception as e:  # the report itself went through; don't fail it over the log
                print(f"Setup log not updated after report: {e}")
            # start.gg's set lists lag a few seconds behind a report: show the result now.
            dq = payload.get("dqLoser")
            scores = {str(e1): -1 if dq == e1 else (0 if dq else s1), str(e2): -1 if dq == e2 else (0 if dq else s2)}
            self.reported[str(set_id)] = {"t": time.time(), "winnerId": v.get("winnerId"), "scores": scores}
        elif kind == "reset":
            self.reported.pop(str(set_id), None)
        elif kind == "start":  # shown as playing if start.gg goes blank while it starts the bracket
            self.mark_started(set_id)
        self.bump()  # bracket changed on start.gg: drop the cache and tell both docks
        self.bump_later()
        return result

    def bump_later(self, delays=(4, 12)):
        """Refetch a few more times after an action: start.gg's set lists catch up over several
        seconds (2026-10-30: a reported set stayed LIVE next to the new set until the 20 s poll)."""
        for d in delays:
            t = threading.Timer(d, self.bump)
            t.daemon = True
            t.start()

    def patch_reported(self, sets):
        """Sets reported in the dock that start.gg still lists as open: show them as done.
        Forgotten once start.gg agrees (or after 2 minutes)."""
        now = time.time()
        out = []
        for s in sets:
            r = self.reported.get(str(s.get("id")))
            if r and (s.get("state") == 3 or now - r["t"] > 120):
                self.reported.pop(str(s["id"]), None)
                r = None
            if r:
                s = {**s, "state": 3, "winnerId": r["winnerId"], "completedAt": int(r["t"]),
                     "slots": [{**sl, "score": r["scores"].get(str(sl.get("entrantId")), sl.get("score"))}
                               for sl in s["slots"]]}
            out.append(s)
        return out


def blank_overlay():
    p = {"entrantId": None, "tag": "", "prefix": "", "display": "", "name": "", "score": 0,
         "imageUrl": "", "character": "", "color": "neutral"}
    return {"round": "", "roundPlain": "", "losersTop8": False, "gameCount": "", "setId": None,
            "p1": dict(p), "p2": dict(p)}


DOCK = None


def ui_version():
    """Changes whenever a dock page file is edited, so open docks reload themselves."""
    try:
        return str(max(os.path.getmtime(os.path.join(STATIC, f)) for f in os.listdir(STATIC)))
    except (OSError, ValueError):
        return "0"


# ---------------------------------------------------------------- HTTP

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".png": "image/png", ".json": "application/json",
        ".otf": "font/otf"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Super Stream Bros Melee/1.0"

    def log_message(self, fmt, *args):
        line = str(args[0]) if args else ""
        if re.search(r"/api/(sets|bracket|changes|state|img|entrant)", line) and " 200 " in " ".join(map(str, args)) + " ":
            return  # don't spam the console with routine polling
        sys.stderr.write("%s  %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def host_ok(self):
        # This PC: only "localhost" names (stops DNS-rebinding tricks from websites). A LAN device that
        # passed lan_gate (PIN) may use any address for the hub.
        if getattr(self, "role", "local") in ("full", "view"):
            return True
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def send(self, code, body, ctype="application/json; charset=utf-8", cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def api_guard(self):
        # Custom header => cross-site pages can't call the API (no CORS preflight answer).
        if not self.host_ok() or self.headers.get("X-Dock") != "1":
            self.send(403, {"error": "forbidden"})
            return False
        return True

    # -- LAN access (lan.py; off unless "lan" + "lanPin" are set in dock_config.json)
    def lan_gate(self, u):
        """Sets self.role ('local' / 'full' / 'view'). Returns True if the request was answered here
        (PIN page, redirect, refusal), False to go on normally."""
        self.role = LAN.role(self)
        if self.role is not None:
            return False
        if not LAN.on:  # not reachable from outside anyway; belt and braces
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

    def serve_file(self, root, rel):
        path = os.path.realpath(os.path.join(root, urllib.parse.unquote(rel)))
        if not path.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(path):
            return self.send(404, {"error": "not found"})
        with open(path, "rb") as f:
            data = f.read()
        self.send(200, data, MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream"),
                  cache=root != STATIC)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if self.lan_gate(u):
            return None
        if not self.host_ok():
            return self.send(403, {"error": "forbidden"})
        if u.path in ("/", "/index.html"):
            return self.serve_file(STATIC, "index.html")
        if u.path in ("/bracket", "/bracket/", "/bracket.html"):
            return self.serve_file(STATIC, "bracket.html")
        if u.path in ("/active", "/active/", "/active.html"):
            return self.serve_file(STATIC, "active.html")
        if u.path.startswith("/static/"):
            return self.serve_file(STATIC, u.path[len("/static/"):])
        if u.path == "/assets/stream_font":  # whichever font file is in assets\fonts\
            font = stream_font()
            return self.serve_file(FONTS, font) if font else self.send(404, {"error": "no font in assets\\fonts"})
        if u.path.startswith("/assets/"):
            return self.serve_file(ASSETS, u.path[len("/assets/"):])
        if not u.path.startswith("/api/") or not self.api_guard():
            return None if u.path.startswith("/api/") else self.send(404, {"error": "not found"})
        try:
            if u.path == "/api/state":
                return self.send(200, {"overlay": DOCK.state, "prefs": DOCK.prefs, "config": public_config(DOCK.config),
                                       "access": self.role,
                                       "tokenSet": bool(get_token()), "outputDir": OUTPUT,
                                       "seasons": list_seasons(), "themesDir": SEASONAL,
                                       "nameBox": name_box(), "uiVersion": ui_version()})
            if u.path == "/api/sets":
                return self.send(200, {**DOCK.sets(), "uiVersion": ui_version()})
            if u.path == "/api/bracket":
                return self.send(200, {**DOCK.bracket(), "overlaySetId": DOCK.state.get("setId"),
                                       "uiVersion": ui_version()})
            if u.path == "/api/changes":
                # Long-poll: returns as soon as anything changes (or after ~25 s).
                q = urllib.parse.parse_qs(u.query)
                since = (q.get("since") or [None])[0]
                version = DOCK.wait_change(int(since) if since not in (None, "") else None)
                return self.send(200, {"version": version, "overlaySetId": DOCK.state.get("setId")})
            if u.path == "/api/entrant":
                q = urllib.parse.parse_qs(u.query)
                return self.send(200, DOCK.entrant_info((q.get("id") or [""])[0]) or {})
            if u.path == "/api/entrants":
                return self.send(200, sorted(DOCK.entrants.values(), key=lambda e: e["tag"].lower()))
            if u.path == "/api/img":
                return self.proxy_image(urllib.parse.parse_qs(u.query).get("url", [""])[0])
        except ApiError as e:
            return self.send(502, {"error": str(e)})
        except Exception as e:  # keep the dock alive
            return self.send(500, {"error": f"{type(e).__name__}: {e}"})
        return self.send(404, {"error": "not found"})

    def proxy_image(self, url):
        p = urllib.parse.urlparse(url)
        if p.scheme != "https" or p.hostname != "images.start.gg":
            return self.send(400, {"error": "only images.start.gg"})
        if url not in DOCK.img_cache:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                DOCK.img_cache[url] = (r.read(5_000_000), r.headers.get("Content-Type", "image/png"))
        data, ctype = DOCK.img_cache[url]
        return self.send(200, data, ctype, cache=True)

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
            payload = json.loads(self.rfile.read(min(n, 10_000_000)).decode("utf-8") or "{}")
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/overlay":
                return self.send(200, {"ok": True, "overlay": DOCK.set_overlay(payload)})
            if u.path == "/api/action":
                result = DOCK.action(payload)
                return self.send(200, {"ok": True, "result": result, "queued": bool((result or {}).get("queued"))})
            if u.path == "/api/theme":
                hexc = re.compile(r"^#[0-9a-fA-F]{6}$")
                theme = {k: payload.get(k) for k in ("accent", "bg", "panel")}
                if not all(isinstance(v, str) and hexc.match(v) for v in theme.values()):
                    raise ValueError("theme colors must be #rrggbb")
                box = payload.get("box") or ""  # bracket overview boxes; empty = panel color
                if box:
                    if not (isinstance(box, str) and hexc.match(box)):
                        raise ValueError("theme colors must be #rrggbb")
                    theme["box"] = box
                DOCK.config["theme"] = theme
                save_json(CONFIG_FILE, DOCK.config)
                DOCK.bump(drop_cache=False)
                return self.send(200, {"ok": True})
            if u.path == "/api/season":
                DOCK.set_season(payload)
                return self.send(200, {"ok": True, "overlay": DOCK.state})
            if u.path == "/api/setup":
                if payload.get("action") == "clear":
                    return self.send(200, DOCK.clear_setup(payload))
                return self.send(200, DOCK.assign_setup(payload))
            if u.path == "/api/setups":
                DOCK.set_setups(payload)
                return self.send(200, {"ok": True, **DOCK.setups_view()})
            if u.path == "/api/stream":
                DOCK.config["streamId"] = payload.get("streamId") or None
                save_json(CONFIG_FILE, DOCK.config)
                DOCK.bump()
                return self.send(200, {"ok": True})
            if u.path == "/api/tournament":
                if payload.get("eventId"):
                    DOCK.config["eventId"] = payload["eventId"]
                    DOCK.entrants = {}
                    save_json(CONFIG_FILE, DOCK.config)
                if "tournamentSlug" in payload:
                    slug = str(payload["tournamentSlug"]).strip().strip("/")
                    m = re.search(r"tournament/([a-z0-9-]+)", slug)  # accept a full URL too
                    DOCK.config["tournamentSlug"] = m.group(1) if m else slug
                t = DOCK.load_tournament(refresh_link=bool(payload.get("refreshLink")))
                DOCK.load_entrants()
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
    os.makedirs(OUTPUT, exist_ok=True)  # not shipped in the package
    DOCK = Dock()
    class Server(ThreadingHTTPServer):
        # On Windows, address reuse lets a second dock bind the same port silently (two docks
        # answering at random, seen 2026-10-30). Without it, a second start fails as intended.
        allow_reuse_address = False

    try:
        srv = Server((HOST, PORT), Handler)
    except OSError:
        print(f"Port {PORT} is busy: the dock is probably already running.")
        return
    if not os.path.isfile(CONFIG_FILE):  # first start: write the settings file so it can be edited
        save_json(CONFIG_FILE, DOCK.config)
    print(f"Super Stream Bros Melee dock running at http://127.0.0.1:{PORT}/")
    print(LAN.describe())
    print(f"Overlay files: {OUTPUT}")
    print(f"Themes: {SEASONAL}")
    print("Stream font:", stream_font() or "none in assets\\fonts (names measured with a system font)")
    if not DOCK.config.get("shortLink"):
        print('Tip: put your series\' start.gg short link in dock_config.json ("shortLink") for "Use latest".')
    print(f"start.gg token ({TOKEN_VAR}):", "found" if get_token() else
          f"NOT SET (set_token.bat{'' if TOKEN_VAR == 'STARTGG_TOKEN' else ' ' + TOKEN_VAR}, then restart)")
    print("Leave this window open during the stream. Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
