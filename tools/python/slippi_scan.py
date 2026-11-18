#!/usr/bin/env python3
"""
slippi_scan.py - build an inventory of Slippi replays (no dependencies).

Usage:
    python tools\\python\\slippi_scan.py "C:\\path\\to\\Protocol #54"          (folder with one subfolder per setup/drive)
    python tools\\python\\slippi_scan.py "C:\\path\\to\\Protocol #54" -o out   (choose where results go)

Writes replay_inventory.json and replay_inventory.csv.

Each .slp is read in place and never modified. For every game it records:
stage, characters, ports, connect codes / display names / nametags (when the
console wrote them), final stocks + percent, winner, length, the Slippi match
id + game number (netplay only), and timing relative to the first replay on the
same setup, because wall-clock times on the Wiis are not trustworthy but the
spacing between games is.

The setup name is the first folder under the root you pass in.
"""
import argparse
import csv
import json
import os
import re
import struct
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

CHARS = ["Captain Falcon", "Donkey Kong", "Fox", "Mr. Game & Watch", "Kirby", "Bowser",
         "Link", "Luigi", "Mario", "Marth", "Mewtwo", "Ness", "Peach", "Pikachu",
         "Ice Climbers", "Jigglypuff", "Samus", "Yoshi", "Zelda", "Sheik", "Falco",
         "Young Link", "Dr. Mario", "Roy", "Pichu", "Ganondorf"]

STAGES = {2: "Fountain of Dreams", 3: "Pokemon Stadium", 4: "Princess Peach's Castle",
          5: "Kongo Jungle", 6: "Brinstar", 7: "Corneria", 8: "Yoshi's Story", 9: "Onett",
          10: "Mute City", 11: "Rainbow Cruise", 12: "Jungle Japes", 13: "Great Bay",
          14: "Hyrule Temple", 15: "Brinstar Depths", 16: "Yoshi's Island", 17: "Green Greens",
          18: "Fourside", 19: "Mushroom Kingdom I", 20: "Mushroom Kingdom II", 22: "Venom",
          23: "Poke Floats", 24: "Big Blue", 25: "Icicle Mountain", 26: "Icetop",
          27: "Flat Zone", 28: "Dream Land N64", 29: "Yoshi's Island N64",
          30: "Kongo Jungle N64", 31: "Battlefield", 32: "Final Destination"}

END_METHODS = {0: "unresolved", 1: "time", 2: "game", 3: "resolved", 7: "no_contest"}
SHORT_GAME_FRAMES = 1800  # under 30 seconds of play


class SlpError(Exception):
    pass


def _text(b, enc):
    try:
        return b.split(b"\x00")[0].decode(enc, "replace").strip()
    except Exception:
        return ""


def _norm_code(s):
    return unicodedata.normalize("NFKC", s)


def read_events(d):
    """Return (game_start, game_end, last_post_frame_by_port, last_frame, incomplete, meta_bytes)."""
    if d[:11] != b"{U\x03raw[$U#l":
        raise SlpError("not a .slp file (missing UBJSON raw header)")
    rawlen = struct.unpack(">I", d[11:15])[0]
    incomplete = rawlen == 0
    raw = d[15:] if incomplete else d[15:15 + rawlen]
    meta = b"" if incomplete else d[15 + rawlen:]
    if not raw or raw[0] != 0x35:
        raise SlpError("missing event payloads block")
    psz = raw[1]
    sizes = {}
    for i in range(0, psz - 1, 3):
        sizes[raw[2 + i]] = struct.unpack(">H", raw[3 + i:5 + i])[0]
    pos = 1 + psz
    gs = ge = None
    last = {}
    last_frame = None
    while pos < len(raw):
        cmd = raw[pos]
        sz = sizes.get(cmd)
        if sz is None or pos + 1 + sz > len(raw):
            incomplete = True  # truncated or unknown event: stop here, keep what we have
            break
        if cmd == 0x36 and gs is None:
            gs = raw[pos:pos + 1 + sz]
        elif cmd == 0x39:
            ge = raw[pos:pos + 1 + sz]
        elif cmd == 0x38 and sz >= 0x21:
            body = raw[pos:pos + 1 + sz]
            if not body[6]:  # skip Nana
                frame = struct.unpack(">i", body[1:5])[0]
                pct = struct.unpack(">f", body[0x16:0x1A])[0]
                last[body[5]] = (body[0x21], round(pct, 1))
                last_frame = frame
        pos += 1 + sz
    if gs is None:
        raise SlpError("no Game Start event")
    return gs, ge, last, last_frame, incomplete, meta


def decode_start(gs):
    n = len(gs)
    info = {"slippi_version": ".".join(str(x) for x in gs[1:4]) if n > 4 else None}
    info["stage_id"] = struct.unpack(">H", gs[0x13:0x15])[0] if n >= 0x15 else None
    info["stage"] = STAGES.get(info["stage_id"], f"Stage {info['stage_id']}")
    info["is_teams"] = bool(gs[0x0D]) if n > 0x0D else None
    players = []
    for i in range(4):
        base = 0x65 + 0x24 * i
        if base + 0x24 > n:
            break
        ext, ptype, stocks, costume = gs[base], gs[base + 1], gs[base + 2], gs[base + 3]
        if ptype == 3:  # empty port
            continue
        p = {"port": i + 1,
             "character": CHARS[ext] if ext < len(CHARS) else f"Char {ext}",
             "costume": costume, "start_stocks": stocks, "type": "human" if ptype == 0 else "cpu"}
        o = 0x161 + 0x10 * i
        p["nametag"] = _text(gs[o:o + 0x10], "shift_jis") if o + 0x10 <= n else ""
        o = 0x1A5 + 0x1F * i
        p["display_name"] = _text(gs[o:o + 0x1F], "utf-8") if o + 0x1F <= n else ""
        o = 0x221 + 0x0A * i
        p["connect_code"] = _norm_code(_text(gs[o:o + 0x0A], "shift_jis")) if o + 0x0A <= n else ""
        players.append(p)
    info["players"] = players
    info["match_id"] = _text(gs[0x2BE:0x2BE + 0x32], "ascii") if n >= 0x2BE + 0x32 else ""
    info["game_number"] = struct.unpack(">I", gs[0x2F1:0x2F5])[0] if n >= 0x2F5 else None
    info["tiebreaker_number"] = struct.unpack(">I", gs[0x2F5:0x2F9])[0] if n >= 0x2F9 else None
    return info


def parse_meta(meta):
    out = {}
    for key in (b"startAt", b"playedOn", b"consoleNick"):
        m = re.search(key + rb"SU", meta)
        if m and m.end() < len(meta):
            ln = meta[m.end()]
            out[key.decode()] = meta[m.end() + 1:m.end() + 1 + ln].decode("utf-8", "replace")
    return out


def decide_winner(players, final, ge):
    ports = [p["port"] for p in players]
    if len(ports) != 2:
        return None, "not_singles"
    if ge is not None and len(ge) > 2 and ge[1] == 7 and ge[2] < 4 and (ge[2] + 1) in ports:
        quitter = ge[2] + 1
        return [p for p in ports if p != quitter][0], "quit"
    a, b = ports
    if a - 1 not in final or b - 1 not in final:
        return None, "no_frame_data"
    (sa, pa), (sb, pb) = final[a - 1], final[b - 1]
    if sa != sb:
        return (a if sa > sb else b), "stocks"
    if pa != pb:
        return (a if pa < pb else b), "percent"
    return None, "tie"


def scan_file(path):
    with open(path, "rb") as f:
        d = f.read()
    gs, ge, final, last_frame, incomplete, meta = read_events(d)
    info = decode_start(gs)
    m = parse_meta(meta)
    winner, how = decide_winner(info["players"], final, ge)
    if ge is None:  # never reached Game End: do not guess a winner from mid-game stocks
        winner, how = None, "no_game_end"
    for p in info["players"]:
        s = final.get(p["port"] - 1)
        p["final_stocks"], p["final_percent"] = (s if s else (None, None))
    start = None
    if m.get("startAt"):
        try:
            start = datetime.fromisoformat(m["startAt"].replace("Z", "+00:00"))
        except ValueError:
            start = None
    time_source = "slp_metadata"
    if start is None:
        start = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        time_source = "file_mtime"
    frames = (last_frame + 123) if last_frame is not None else None
    flags = []
    if incomplete:
        flags.append("incomplete")
    if last_frame is not None and last_frame < SHORT_GAME_FRAMES:
        flags.append("short_game")
    if how == "not_singles":
        flags.append("not_singles")
    end_method = END_METHODS.get(ge[1], f"method_{ge[1]}") if ge and len(ge) > 1 else "unknown"
    return {"file": os.path.basename(path), "start_utc": start.isoformat(), "time_source": time_source,
            "duration_s": round(frames / 60, 1) if frames else None, "last_frame": last_frame,
            "played_on": m.get("playedOn", ""), "console_nick": m.get("consoleNick", ""),
            "end_method": end_method, "winner_port": winner, "winner_basis": how,
            "flags": flags, **info}


def collect(root):
    rows, errors = [], []
    for dirpath, _, files in os.walk(root):
        for fn in sorted(files):
            if not fn.lower().endswith(".slp"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            parts = rel.split(os.sep)
            setup = parts[0] if len(parts) > 1 else "(root)"
            try:
                row = scan_file(full)
            except (SlpError, struct.error, OSError, IndexError) as e:
                errors.append({"path": rel, "error": str(e)})
                continue
            row["setup"], row["path"] = setup, rel
            rows.append(row)
    # timing relative to the first replay on each setup
    by_setup = {}
    for r in rows:
        by_setup.setdefault(r["setup"], []).append(r)
    for rs in by_setup.values():
        rs.sort(key=lambda r: r["start_utc"])
        t0 = datetime.fromisoformat(rs[0]["start_utc"])
        prev_end = None
        for r in rs:
            t = datetime.fromisoformat(r["start_utc"])
            r["rel_start_s"] = round((t - t0).total_seconds(), 1)
            r["gap_from_prev_s"] = round((t - prev_end).total_seconds(), 1) if prev_end else None
            prev_end = t + timedelta(seconds=r["duration_s"] or 0)
    rows.sort(key=lambda r: (r["setup"], r["rel_start_s"]))
    return rows, errors


def write_outputs(rows, errors, outdir):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "replay_inventory.json"), "w", encoding="utf-8") as f:
        json.dump({"replays": rows, "errors": errors}, f, indent=2, ensure_ascii=False)
    cols = ["setup", "file", "start_utc", "rel_start_s", "gap_from_prev_s", "duration_s", "stage",
            "p1_port", "p1_character", "p1_code", "p1_name", "p1_tag", "p1_stocks", "p1_percent",
            "p2_port", "p2_character", "p2_code", "p2_name", "p2_tag", "p2_stocks", "p2_percent",
            "winner_port", "winner_basis", "end_method", "match_id", "game_number",
            "slippi_version", "played_on", "flags", "path"]
    with open(os.path.join(outdir, "replay_inventory.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            row = {c: r.get(c, "") for c in cols}
            row["flags"] = ";".join(r["flags"])
            for n, p in enumerate(r["players"][:2], start=1):
                row.update({f"p{n}_port": p["port"], f"p{n}_character": p["character"],
                            f"p{n}_code": p["connect_code"], f"p{n}_name": p["display_name"],
                            f"p{n}_tag": p["nametag"], f"p{n}_stocks": p["final_stocks"],
                            f"p{n}_percent": p["final_percent"]})
            w.writerow(row)


def main():
    ap = argparse.ArgumentParser(description="Inventory Slippi replays.")
    ap.add_argument("root", help="folder containing .slp files (one subfolder per setup)")
    ap.add_argument("-o", "--out", default=None, help="output folder (default: <root>/_scan)")
    a = ap.parse_args()
    if not os.path.isdir(a.root):
        sys.exit(f"Not a folder: {a.root}")
    out = a.out or os.path.join(a.root, "_scan")
    rows, errors = collect(a.root)
    write_outputs(rows, errors, out)
    print(f"Scanned {len(rows)} replays ({len(errors)} unreadable). Results in: {out}")
    for setup in sorted({r['setup'] for r in rows}):
        rs = [r for r in rows if r["setup"] == setup]
        short = sum("short_game" in r["flags"] for r in rs)
        coded = sum(bool(p["connect_code"]) for r in rs for p in r["players"])
        print(f"  {setup}: {len(rs)} games, {short} short, "
              f"{'connect codes present' if coded else 'no connect codes'}")
    for e in errors[:10]:
        print(f"  skipped {e['path']}: {e['error']}")


if __name__ == "__main__":
    main()
