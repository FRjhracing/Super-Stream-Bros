#!/usr/bin/env python3
"""
youtube_upload.py - upload a tournament's videos to YouTube from its upload kit.

One-time setup (see README "YouTube upload"):
    1. Google Cloud project with "YouTube Data API v3" (+ "Google Drive API" for rclone) enabled,
       OAuth consent screen published ("In production"), OAuth client type "Desktop app".
    2. Download the client JSON to %APPDATA%\\ProtocolVOD\\client_secret.json
    3. python tools\\python\\youtube_upload.py auth          (browser opens; sign in with the channel's account)

Weekly:
    python tools\\python\\youtube_upload.py upload "I:\\Protocol VOD\\Melee\\Protocol #58"   [--privacy private|unlisted|public]
    python tools\\python\\youtube_upload.py status "I:\\Protocol VOD\\Melee\\Protocol #58"
    python tools\\python\\youtube_upload.py links  "I:\\Protocol VOD\\Melee\\Protocol #58"   (Lucky Stats link in, dead Drive links out)

- Reads <folder>\\upload_kit\\upload_kit.json (written by vod_cutter.py kit/render).
- Uploads in kit order (Full VODs, then sets in play order) and adds each video to a playlist
  named after the tournament (created once). Progress is saved in upload_kit\\uploaded.json, so a
  rerun skips what is already up: when the daily API quota runs out it stops cleanly, run it again
  the next day.
- Until the Google project passes YouTube's API audit, YouTube forces API uploads to Private
  whatever --privacy says; publish them in YouTube Studio (select all > Visibility).
- Secrets (client secret, refresh token) live only in %APPDATA%\\ProtocolVOD\\, never in the project
  or the output. Stdlib only.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

# Prefer IPv4 (same reason as vod_cutter.py / the dock: flaky IPv6 on the laptop's network).
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: sorted(_getaddrinfo(*a, **k), key=lambda r: r[0] != socket.AF_INET)

SECRET_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ProtocolVOD")
CLIENT_FILE = os.path.join(SECRET_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(SECRET_DIR, "youtube_token.json")
SCOPE = "https://www.googleapis.com/auth/youtube"  # upload + playlists
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 64 * 1024 * 1024
GAMING = "20"
# Tags the user set by hand on the #57 uploads (2026-10-30). A kit's "tags" list overrides them.
DEFAULT_TAGS = ["Melee", "Smash Bros", "Weekly", "Tournament", "Luigi", "Marth", "Captain Falcon",
                "Doctor Mario", "Sheik", "Fox", "Falco"]


def set_account(name):
    """Second channel/account (e.g. "sova"): its own client JSON and sign-in, side by side with the default."""
    global CLIENT_FILE, TOKEN_FILE
    if name:
        CLIENT_FILE = os.path.join(SECRET_DIR, f"client_secret_{name}.json")
        TOKEN_FILE = os.path.join(SECRET_DIR, f"youtube_token_{name}.json")


class QuotaExceeded(Exception):
    pass


# ---------------------------------------------------------------- OAuth

def load_client():
    if not os.path.isfile(CLIENT_FILE):
        raise SystemExit(f"Client file missing: {CLIENT_FILE}\n"
                         "Download the OAuth client (Desktop app) JSON from Google Cloud and save it there.")
    with open(CLIENT_FILE, encoding="utf-8") as f:
        d = json.load(f)
    c = d.get("installed") or d.get("web") or d
    return c["client_id"], c["client_secret"]


def post_form(url, fields):
    req = urllib.request.Request(url, urllib.parse.urlencode(fields).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"Google sign-in failed ({e.code}): {body[:300]}")


def save_token(tok):
    os.makedirs(SECRET_DIR, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f)


def auth():
    """Loopback OAuth with PKCE: a one-shot local server catches Google's redirect."""
    cid, csec = load_client()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Signed in. You can close this tab." if "code" in got else "Sign-in failed or was cancelled."
            self.wfile.write(f"<p style='font:16px sans-serif'>{msg}</p>".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Opening the browser for Google sign-in (use the account that owns the YouTube channel).")
    print("If it doesn't open, paste this into the browser:\n" + url)
    webbrowser.open(url)
    srv.timeout = 300
    while not got:
        srv.handle_request()
    srv.server_close()
    if "code" not in got:
        raise SystemExit(f"Sign-in failed: {got.get('error', 'no code')}")
    tok = post_form(TOKEN_URL, {"code": got["code"], "client_id": cid, "client_secret": csec,
                                "redirect_uri": redirect, "grant_type": "authorization_code",
                                "code_verifier": verifier})
    if "refresh_token" not in tok:
        raise SystemExit("Google returned no refresh token; run auth again.")
    save_token({"refresh_token": tok["refresh_token"]})
    ch = api("GET", "/channels", {"part": "snippet", "mine": "true"})
    names = [c["snippet"]["title"] for c in ch.get("items", [])]
    print(f"Signed in. Channel: {', '.join(names) or '(none found on this account)'}")


_access = {"token": None, "until": 0}


def access_token():
    if _access["token"] and time.time() < _access["until"] - 60:
        return _access["token"]
    if not os.path.isfile(TOKEN_FILE):
        raise SystemExit("Not signed in: run  python tools\\python\\youtube_upload.py auth")
    with open(TOKEN_FILE, encoding="utf-8") as f:
        refresh = json.load(f)["refresh_token"]
    cid, csec = load_client()
    tok = post_form(TOKEN_URL, {"refresh_token": refresh, "client_id": cid, "client_secret": csec,
                                "grant_type": "refresh_token"})
    _access.update(token=tok["access_token"], until=time.time() + tok.get("expires_in", 3600))
    return _access["token"]


# ---------------------------------------------------------------- API

def check_quota(e, body):
    if e.code == 403 and ("quotaExceeded" in body or "uploadLimitExceeded" in body):
        raise QuotaExceeded(body)


class ApiError(SystemExit):
    pass


def api(method, path, params=None, body=None, tries=5):
    """Calls the Data API. Retries YouTube's temporary errors (409 ABORTED/SERVICE_UNAVAILABLE, 5xx)."""
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, data, {"Authorization": "Bearer " + access_token(),
                                                 "Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            check_quota(e, txt)
            temporary = e.code >= 500 or (e.code == 409 and ("ABORTED" in txt or "SERVICE_UNAVAILABLE" in txt))
            if not temporary or attempt == tries:
                raise ApiError(f"YouTube API {method} {path} failed ({e.code}): {txt[:400]}")
        except OSError as e:
            if attempt == tries:
                raise ApiError(f"YouTube API {method} {path} failed: {e}")
        time.sleep(min(60, 5 * 2 ** (attempt - 1)))


def clean_text(s, limit):
    # YouTube rejects < and > in titles/descriptions.
    return s.replace("<", "(").replace(">", ")")[:limit]


def start_upload(video, privacy):
    size = os.path.getsize(video["file"])
    meta = {"snippet": {"title": clean_text(video["title"], 100),
                        "description": clean_text(video["description"], 5000), "categoryId": GAMING,
                        "tags": video.get("tags") or DEFAULT_TAGS},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    req = urllib.request.Request(
        UPLOAD_API + "?uploadType=resumable&part=snippet,status", json.dumps(meta).encode(),
        {"Authorization": "Bearer " + access_token(), "Content-Type": "application/json; charset=UTF-8",
         "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.headers["Location"]
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")
        check_quota(e, txt)
        raise SystemExit(f"Upload start failed ({e.code}): {txt[:400]}")


def set_thumbnail(video_id, path):
    """Custom thumbnail (thumbnails.set, ~50 units). Needs a phone-verified channel; failures only warn."""
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?" + urllib.parse.urlencode(
            {"videoId": video_id, "uploadType": "media"}), data,
        {"Authorization": "Bearer " + access_token(), "Content-Type": "image/jpeg"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120):
            return True
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")
        check_quota(e, txt)
        print(f"    thumbnail not set ({e.code}): {txt[:200]}")
        return False


def put(session, data, rng):
    req = urllib.request.Request(session, data, {"Authorization": "Bearer " + access_token(),
                                                 "Content-Range": rng}, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def uploaded_bytes(session, size):
    """Ask the session how far it got (after a dropped connection)."""
    code, headers, _ = put(session, b"", f"bytes */{size}")
    if code in (200, 201):
        return size
    rng = headers.get("Range") if headers else None
    return int(rng.split("-")[1]) + 1 if rng else 0


def send_file(session, path):
    size = os.path.getsize(path)
    pos, tries, t0 = 0, 0, time.time()
    with open(path, "rb") as f:
        while True:
            f.seek(pos)
            data = f.read(CHUNK)
            end = pos + len(data) - 1
            try:
                code, headers, body = put(session, data, f"bytes {pos}-{end}/{size}")
            except OSError as e:  # connection dropped: ask where to continue
                code, body = None, str(e).encode()
            if code in (200, 201):
                print(f"\r    100%  {size / 1e9:.2f} GB in {(time.time() - t0) / 60:.1f} min          ")
                return json.loads(body)
            if code == 308:
                rng = headers.get("Range")
                pos, tries = (int(rng.split("-")[1]) + 1 if rng else 0), 0
                rate = pos / max(1.0, time.time() - t0) / 1e6
                print(f"\r    {pos * 100 // size:3d}%  {pos / 1e9:.2f}/{size / 1e9:.2f} GB  {rate:.1f} MB/s   ",
                      end="", flush=True)
                continue
            tries += 1
            if code and 400 <= code < 500 and code not in (408, 429):
                raise SystemExit(f"\nUpload failed ({code}): {body[:400]!r}")
            if tries > 8:
                raise SystemExit(f"\nUpload kept failing ({code}); rerun later, it resumes from the next video.")
            wait = min(60, 2 ** tries)
            print(f"\n    retry in {wait} s ({code or body[:80]!r})")
            time.sleep(wait)
            pos = uploaded_bytes(session, size)


# ---------------------------------------------------------------- weekly

ACCOUNT = {"name": None}  # set in main(); each account keeps its own progress file


def kit_paths(folder):
    kit = os.path.join(folder, "upload_kit")
    state = f"uploaded_{ACCOUNT['name']}.json" if ACCOUNT["name"] else "uploaded.json"
    return os.path.join(kit, "upload_kit.json"), os.path.join(kit, state)


def video_title(kit, title):
    """On a second account the game goes after the tournament: "PROTOCOL #58 Melee: Grand Final - ..."."""
    t = kit["tournament"]
    if ACCOUNT["name"] and title.startswith(t + ":"):
        game = kit.get("game") or "Melee"
        title = f"{t} {game}{title[len(t):]}"
    return title


def playlist_name(kit):
    """Tournament playlist. On a second account (SoVA hosts Melee and Ultimate) it gets the game:
    "PROTOCOL #58 Melee" / "PROTOCOL #58 Ultimate". A kit's "game" sets it (default Melee)."""
    name = kit.get("playlist") or kit["tournament"]
    if ACCOUNT["name"]:
        game = kit.get("game") or "Melee"
        if game.lower() not in name.lower():
            name = f"{name} {game}"
    return name


def load_state(path):
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"videos": {}, "playlist": None}


def save_state(path, st):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)


def ensure_playlist(st, state_file, name, privacy):
    """The tournament's playlist: saved id, else one of ours with the same title, else a new one."""
    if st.get("playlist"):
        return st["playlist"]
    title = clean_text(name, 150)
    page = None
    while True:
        params = {"part": "snippet", "mine": "true", "maxResults": 50}
        if page:
            params["pageToken"] = page
        r = api("GET", "/playlists", params)
        for pl in r.get("items", []):
            if pl["snippet"]["title"] == title:
                st["playlist"] = pl["id"]
        page = r.get("nextPageToken")
        if st.get("playlist") or not page:
            break
    if not st.get("playlist"):
        pl = api("POST", "/playlists", {"part": "snippet,status"},
                 {"snippet": {"title": title}, "status": {"privacyStatus": privacy}})
        st["playlist"] = pl["id"]
    save_state(state_file, st)
    return st["playlist"]


def sync_playlist_description(st, kit):
    """Playlist description from the kit's "playlist_description" (bracket, replays, Lucky Stats event).
    playlists.update, ~50 units; skipped when it already matches. Failures only warn."""
    want = kit.get("playlist_description")
    if not st.get("playlist") or not want:
        return
    try:
        r = api("GET", "/playlists", {"part": "snippet", "id": st["playlist"]})
        if not r.get("items"):
            return
        sn = r["items"][0]["snippet"]
        want = clean_text(want, 5000)
        if sn.get("description", "").strip() == want.strip():
            return
        body = {"id": st["playlist"], "snippet": {"title": sn["title"], "description": want}}
        if sn.get("defaultLanguage"):
            body["snippet"]["defaultLanguage"] = sn["defaultLanguage"]
        api("PUT", "/playlists", {"part": "snippet"}, body)
        print(f"  playlist description updated: {sn['title']}")
    except ApiError as e:
        print(f"    playlist description not updated ({str(e)[:120]}); retried on the next run")


def add_missing_to_playlist(st, state_file, kit, privacy):
    """Put every uploaded video that isn't in the playlist yet into it. Failures are reported, not fatal."""
    order = {os.path.basename(v["file"]): i for i, v in enumerate(kit["videos"])}
    missing = [e for name, e in sorted(st["videos"].items(), key=lambda kv: order.get(kv[0], 1 << 30))
               if not e.get("playlist")]
    if not missing:
        return
    try:
        pid = ensure_playlist(st, state_file, playlist_name(kit), privacy)
    except ApiError as e:
        print(f"    playlist not available now ({e}); retried on the next run")
        return
    for entry in missing:
        try:
            api("POST", "/playlistItems", {"part": "snippet"},
                {"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": entry["id"]}}})
        except ApiError as e:
            print(f"    not added to the playlist yet: {entry['title']} ({str(e)[:120]}); retried on the next run")
            continue
        entry["playlist"] = pid
        save_state(state_file, st)
    sync_playlist_description(st, kit)


def upload(folder, privacy, playlist=True, limit=None, only_check=False):
    kit_file, state_file = kit_paths(folder)
    if not os.path.isfile(kit_file):
        raise SystemExit(f"No {kit_file}: run  python tools\\python\\vod_cutter.py kit <vod_config.json>  first.")
    with open(kit_file, encoding="utf-8") as f:
        kit = json.load(f)
    st = load_state(state_file)
    todo = [v for v in kit["videos"] if os.path.basename(v["file"]) not in st["videos"]]
    print(f"{kit['tournament']}: {len(kit['videos'])} videos, {len(kit['videos']) - len(todo)} already up, "
          f"{len(todo)} to go.")
    if only_check:  # just the sets held private for the TO to confirm
        todo = [v for v in todo if v.get("check")]
        print(f"Only the {len(todo)} sets marked to check this run.")
    done = 0
    try:
        if playlist and not todo:
            add_missing_to_playlist(st, state_file, kit, privacy)
        for v in todo:
            if limit is not None and done >= limit:
                break
            name = os.path.basename(v["file"])
            if not os.path.isfile(v["file"]):
                print(f"  missing, skipped: {name}")
                continue
            print(f"  {v['title']}")
            v = dict(v, tags=v.get("tags") or kit_tags(kit), title=video_title(kit, v["title"]))
            session = start_upload(v, v.get("privacy") or privacy)  # kit can hold a video private (sets to check)
            res = send_file(session, v["file"])
            entry = {"id": res["id"], "url": f"https://youtu.be/{res['id']}", "title": v["title"],
                     "privacy": res.get("status", {}).get("privacyStatus", privacy),
                     "uploaded": time.strftime("%Y-%m-%d %H:%M")}
            st["videos"][name] = entry
            save_state(state_file, st)
            print(f"    {entry['url']} ({entry['privacy']})")
            if v.get("thumbnail") and os.path.isfile(v["thumbnail"]) and set_thumbnail(res["id"], v["thumbnail"]):
                entry["thumbnail"] = os.path.basename(v["thumbnail"])
                save_state(state_file, st)
            done += 1
    except QuotaExceeded:
        save_state(state_file, st)
        if playlist:
            add_missing_to_playlist(st, state_file, kit, privacy)
        left = len([v for v in kit["videos"] if os.path.basename(v["file"]) not in st["videos"]])
        print(f"\nYouTube's daily API quota is used up ({left} videos left). Run the same command again "
              "tomorrow (quota resets at midnight Pacific); it continues where it stopped.")
        return
    if playlist and done:
        add_missing_to_playlist(st, state_file, kit, privacy)  # the whole playlist in kit order
    left = len([v for v in kit["videos"] if os.path.basename(v["file"]) not in st["videos"]])
    print(f"\nDone: {done} uploaded this run, {left} left." + (
        "\nNote: until the Google project passes YouTube's audit, API uploads are Private; publish them "
        "in YouTube Studio." if privacy != "private" else ""))


def status(folder):
    kit_file, state_file = kit_paths(folder)
    with open(kit_file, encoding="utf-8") as f:
        kit = json.load(f)
    st = load_state(state_file)
    for v in kit["videos"]:
        e = st["videos"].get(os.path.basename(v["file"]))
        print(f"  {'UP  ' + e['url'] if e else 'todo':30} {v['title']}")
    if st.get("playlist"):
        print(f"Playlist: https://www.youtube.com/playlist?list={st['playlist']}")


def kit_tags(kit):
    return kit.get("tags") or DEFAULT_TAGS


def set_tags(folder):
    """Bring already-uploaded videos in line with the kit: tags, title (the game designation on a second
    account) and description (e.g. Lucky Stats links added after upload). videos.update, ~50 units each; skips videos that already match."""
    kit_file, state_file = kit_paths(folder)
    with open(kit_file, encoding="utf-8") as f:
        kit = json.load(f)
    st = load_state(state_file)
    by_id = {e["id"]: name for name, e in st["videos"].items()}
    kit_by_file = {os.path.basename(x["file"]): x for x in kit["videos"]}
    ids = list(by_id)
    changed = 0
    for k in range(0, len(ids), 50):
        r = api("GET", "/videos", {"part": "snippet", "id": ",".join(ids[k:k + 50])})
        for v in r.get("items", []):
            sn = v["snippet"]
            kv = kit_by_file.get(by_id[v["id"]], {})
            want = kv.get("tags") or kit_tags(kit)
            title = clean_text(video_title(kit, kv["title"]), 100) if kv.get("title") else sn["title"]
            desc = clean_text(kv["description"], 5000) if kv.get("description") else sn.get("description", "")
            if (sorted(t.lower() for t in sn.get("tags") or []) == sorted(t.lower() for t in want)
                    and sn["title"] == title and sn.get("description", "").strip() == desc.strip()):
                continue
            body = {"id": v["id"], "snippet": {"title": title, "description": desc,
                                               "categoryId": sn.get("categoryId", GAMING), "tags": want}}
            for key in ("defaultLanguage", "defaultAudioLanguage"):
                if sn.get(key):
                    body["snippet"][key] = sn[key]
            api("PUT", "/videos", {"part": "snippet"}, body)
            changed += 1
            print(f"  updated: {title}")
    print(f"Updated {changed} video(s); {len(ids) - changed} already matched.")
    sync_playlist_description(st, kit)
    for name, e in st["videos"].items():
        kv = kit_by_file.get(name, {})
        th = kv.get("thumbnail")
        if th and os.path.isfile(th) and e.get("thumbnail") != os.path.basename(th) and set_thumbnail(e["id"], th):
            e["thumbnail"] = os.path.basename(th)
            save_state(state_file, st)
            print(f"  thumbnail set: {e['title']}")


LS_LABEL = "Lucky Stats replays and analysis"  # same label as vod_cutter.py
RCLONE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "tools", "rclone", "rclone.exe")


def live_drive_ids():
    """IDs of the folders on gdrive: (two levels: tournament + per-setup). None if rclone fails."""
    import subprocess
    try:
        out = subprocess.run([RCLONE, "lsjson", "gdrive:", "--dirs-only", "--max-depth", "2"],
                             capture_output=True, timeout=300)
        ids = {x.get("ID") for x in json.loads(out.stdout.decode("utf-8-sig"))} - {None}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return ids if out.returncode == 0 and ids else None


def fix_link_lines(text, ls_url, live_ids):
    """Adds the Lucky Stats event line after the link block if missing; drops "Replays:" Drive links whose
    folder no longer exists (deleted after 2 weeks; Lucky Stats hosts the replays)."""
    lines = text.split("\n")
    if live_ids is not None:
        def dead(l):
            if not l.startswith("Replays: https://drive.google.com/drive/folders/"):
                return False
            fid = l.split("/folders/", 1)[1].split("?", 1)[0].strip()
            return fid not in live_ids
        lines = [l for l in lines if not dead(l)]
    if ls_url and not any(l.startswith(LS_LABEL) for l in lines):
        at = 0
        for i, l in enumerate(lines):
            if l.startswith(("Replays: ", "Bracket: ")):
                at = i + 1
            elif l.strip():
                break
        lines.insert(at, f"{LS_LABEL}: {ls_url}")
    return "\n".join(lines)


def fix_links(folder):
    """Edits the LIVE descriptions (videos + playlist; manual edits in Studio are kept) and the kit:
    Lucky Stats event link from vod_config "luckystats._event", dead Drive replay links removed.
    videos.update ~50 units per changed video."""
    kit_file, state_file = kit_paths(folder)
    with open(kit_file, encoding="utf-8") as f:
        kit = json.load(f)
    st = load_state(state_file)
    ls_url = None
    try:
        with open(os.path.join(folder, "vod_config.json"), encoding="utf-8-sig") as f:
            ls_url = (json.load(f).get("luckystats") or {}).get("_event")
    except (OSError, ValueError):
        pass
    live = live_drive_ids()
    if live is None:
        print("  Drive listing failed: replay links left as they are")
    ids = {e["id"] for e in st["videos"].values()}
    changed = 0
    idl = list(ids)
    for k in range(0, len(idl), 50):
        r = api("GET", "/videos", {"part": "snippet", "id": ",".join(idl[k:k + 50])})
        for v in r.get("items", []):
            sn = v["snippet"]
            old = sn.get("description", "")
            new = fix_link_lines(old, ls_url, live)
            if new == old:
                continue
            body = {"id": v["id"], "snippet": {"title": sn["title"], "description": clean_text(new, 5000),
                                               "categoryId": sn.get("categoryId", GAMING), "tags": sn.get("tags") or []}}
            for key in ("defaultLanguage", "defaultAudioLanguage"):
                if sn.get(key):
                    body["snippet"][key] = sn[key]
            api("PUT", "/videos", {"part": "snippet"}, body)
            changed += 1
            print(f"  updated: {sn['title']}")
    print(f"Updated {changed} video(s); {len(ids) - changed} already fine.")
    # Keep the kit in step, so a later "tags" run doesn't put the old links back.
    for v in kit["videos"]:
        v["description"] = fix_link_lines(v.get("description", ""), ls_url, live)
    base = kit.get("playlist_description")
    if base is None and st.get("playlist"):  # older kits: start from the live playlist description
        r = api("GET", "/playlists", {"part": "snippet", "id": st["playlist"]})
        base = r["items"][0]["snippet"].get("description", "") if r.get("items") else ""
    kit["playlist_description"] = fix_link_lines(base or "", ls_url, live).strip("\n")
    with open(kit_file, "w", encoding="utf-8") as f:
        json.dump(kit, f, indent=2, ensure_ascii=False)
    if st.get("playlist") and kit["playlist_description"]:
        sync_playlist_description(st, kit)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Upload a tournament's upload kit to YouTube.")
    ap.add_argument("command", choices=["auth", "upload", "status", "tags", "links"])
    ap.add_argument("--account", help='second channel, e.g. "sova": uses client_secret_sova.json / '
                                      "youtube_token_sova.json in %%APPDATA%%\\ProtocolVOD")
    ap.add_argument("folder", nargs="?", help=r'tournament output folder, e.g. "I:\Protocol VOD\Melee\Protocol #59"')
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--no-playlist", action="store_true")
    ap.add_argument("--limit", type=int, help="upload at most this many videos this run")
    ap.add_argument("--only-check", action="store_true", help="upload only the kit's sets marked to check (held private)")
    a = ap.parse_args()
    account = a.account
    if not account and a.folder:  # a kit can name its account (Ultimate kits -> "sova")
        try:
            with open(kit_paths(a.folder)[0], encoding="utf-8") as f:
                account = json.load(f).get("account")
        except (OSError, ValueError):
            pass
    set_account(account)
    ACCOUNT["name"] = account
    if account:
        print(f"Account: {account}")
    if a.command == "auth":
        auth()
        return
    if not a.folder:
        ap.error("folder is required")
    if a.command == "upload":
        upload(a.folder, a.privacy, not a.no_playlist, a.limit, a.only_check)
    elif a.command == "tags":
        set_tags(a.folder)
    elif a.command == "links":
        fix_links(a.folder)
    else:
        status(a.folder)


if __name__ == "__main__":
    main()
