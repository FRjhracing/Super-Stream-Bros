"""Lucky Stats export: one folder per matched set, numbered .slp copies + context.json.

Usage (from the project root):
    python tools\\python\\luckystats_export.py "I:/Protocol VOD/Melee/Protocol #59/plan.json" "Local Replays/Protocol #59" "LuckyStats/Protocol #59/sets"
    python tools\\python\\luckystats_export.py <plan.json> <replays dir> <out dir> [--repaired <dir>]

context.json follows auto-vlerk-game-data-mapper's buildContext (github.com/0xburn/auto-vlerk-game-data-mapper):
bestOf, startMs, scores (score before each game), finalScore, players, startgg ids, mapping (files + sha256).
That tool can't map our sets (start.gg has no per-game character reports here), so the games come from the
VOD cutter's reviewed plan instead. startMs is the corrected real time (laptop_time), since the Wii clocks are wrong.
Replays are only read and copied; originals are never changed.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools\\python
from vod_cutter import gql  # start.gg client (IPv4-first, token from STARTGG_TOKEN)

# Lucky Stats / slippi-js names
CHAR_NAMES = {"Doctor Mario": "Dr. Mario", "Mr Game & Watch": "Mr. Game & Watch", "Game & Watch": "Mr. Game & Watch"}


def char(name):
    return CHAR_NAMES.get(name, name)


def event_ids(set_id):
    q = """query($id: ID!) { set(id: $id) { event { id name tournament { id name } } } }"""
    ev = gql(q, {"id": set_id})["set"]["event"]
    return ev


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(seg, ev, files):
    ports = [seg["a"]["port"], seg["b"]["port"]]
    ents = [seg["a"], seg["b"]]
    counts = [0, 0]

    def slots():
        return [{"displayNames": [e["tag"]], "prefixes": [e.get("prefix") or ""], "pronouns": [""],
                 "ports": [ports[i]], "score": counts[i]} for i, e in enumerate(ents)]

    scores = []
    for g in seg["games"]:
        scores.append({"slots": slots()})
        counts[0 if g["winner_port"] == ports[0] else 1] += 1
    if counts != [seg["a"]["score"], seg["b"]["score"]]:
        raise SystemExit(f"set {seg['id']}: games give {counts}, start.gg says "
                         f"{seg['a']['score']}-{seg['b']['score']}")
    first = datetime.datetime.strptime(seg["games"][0]["laptop_time"], "%Y-%m-%d %H:%M:%S")
    players = {}
    for i, e in enumerate(ents):
        seen = []
        for g in seg["games"]:
            c = char(next(p["character"] for p in g["players"] if p["port"] == ports[i]))
            if c not in seen:
                seen.append(c)
        players[f"entrant{i + 1}"] = [{"name": e["tag"], "characters": seen}]
    return {
        "bestOf": max(counts) * 2 - 1,
        "startMs": int(first.timestamp() * 1000),  # local laptop clock -> epoch ms
        "scores": scores,
        "finalScore": {"slots": slots()},
        "players": players,
        "startgg": {"tournament": {"id": ev["tournament"]["id"], "name": ev["tournament"]["name"]},
                    "event": {"id": ev["id"], "name": ev["name"]},
                    "set": {"id": seg["setId"], "fullRoundText": seg["round"]}},
        "mapping": {"generatedBy": "protocol-vod-cutter", "version": 1,
                    "evidence": "start.gg set matched to replays by setup, timing and character/score sequence; "
                                "reviewed by the TO",
                    "files": files},
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("replays")
    ap.add_argument("out")
    ap.add_argument("--repaired", help="folder with repaired copies (used for games marked repaired)")
    a = ap.parse_args()
    with open(a.plan, encoding="utf-8") as f:
        plan = json.load(f)
    segs = [s for s in plan["segments"] if s.get("setId") and s.get("games")]
    ev = event_ids(segs[0]["setId"])
    print(f"{ev['tournament']['name']} / {ev['name']} (event {ev['id']}): {len(segs)} sets")
    os.makedirs(a.out, exist_ok=True)
    done = skipped = 0
    for s in segs:
        # Video-only flags (recording started late / ran out, games rebuilt from replays) don't affect the replays.
        bad = [f for f in s.get("flags", []) if not f.startswith(("first game started", "set runs past", "game(s) "))]
        if bad:
            print(f"  skip {s['id']} ({s['round']}): flags {bad}")
            skipped += 1
            continue
        d = os.path.join(a.out, f"set-{s['setId']}")
        if os.path.exists(os.path.join(d, "context.json")):
            skipped += 1
            continue
        tmp = d + ".partial"
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp)
        files = []
        for i, g in enumerate(s["games"]):
            src = os.path.join(a.replays, g["file"])
            if g.get("repaired"):
                if not a.repaired:
                    raise SystemExit(f"set {s['id']}: {g['file']} needs --repaired")
                src = os.path.join(a.repaired, os.path.basename(g["file"]))
            name = f"{i + 1:02d}.slp"
            shutil.copy2(src, os.path.join(tmp, name))
            files.append({"name": name, "sha256": sha256(src)})
        ctx = build(s, ev, files)
        with open(os.path.join(tmp, "context.json"), "w", encoding="utf-8") as f:
            json.dump(ctx, f, indent=2, ensure_ascii=False)
        os.replace(tmp, d)
        done += 1
        a_, b_ = s["a"], s["b"]
        print(f"  set-{s['setId']}  {s['id']:>2} {s['round']}: {a_['tag']} {a_['score']}-{b_['score']} {b_['tag']} "
              f"({len(files)} games)")
    print(f"Done: {done} written, {skipped} skipped -> {a.out}")


if __name__ == "__main__":
    main()
