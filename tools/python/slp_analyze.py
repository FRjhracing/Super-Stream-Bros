"""Frame-by-frame set analysis from .slp replays (stdlib only; replays are only read).

Usage (from the project root):
    python tools\\python\\slp_analyze.py <player tag or port> <game1.slp> [game2.slp ...]    -> text report
    python tools\\python\\slp_analyze.py --json ...                                           -> raw numbers

"me" is picked by port number (1-4) or, with a tag, by the character that player used in the
plan (pass --char "Captain Falcon"). Stats follow Slippi/Lucky Stats definitions where they exist
(conversions end after 45 frames of the victim being free; opening = neutral win / counter / trade),
plus extra reads for coaching: what you were doing when you got opened, what you did right after
hitstun, grab attempts, tech-chase follow-ups, crouch -> dashback, pace (inputs/min) per stock.
"""
import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools\\python
import slippi_scan  # noqa: E402

# ---- action states (shared ids)
DEAD = range(0x00, 0x0B)
REBIRTH = (0x0C, 0x0D)
DAMAGE = set(range(0x4B, 0x5C)) | {0x26, 0xB9, 0xC1}          # hitstun / tumble / down-damage
GRABBED = set(range(0xDF, 0xE9))
DOWN = set(range(0xB7, 0xC7))                                  # missed tech / lying / getups
TECH = set(range(0xC7, 0xCD))                                  # tech in place / rolls / wall/ceiling techs
MISSED_TECH = {0xB7, 0xBF}
TECH_NAMES = {0xC7: "tech in place", 0xC8: "tech roll forward", 0xC9: "tech roll back"}
SQUAT = {0x27, 0x28, 0x29}
DASH, TURN = 0x14, 0x12
GRAB_START = {0xD4, 0xD6}            # Catch, CatchDash
GRAB_HOLD = {0xD5, 0xD7, 0xD8}       # CatchPull, CatchDashPull, CatchWait
SHIELD = {0xB2, 0xB3, 0xB4, 0xB5}
LEDGE = set(range(0xFC, 0x108))
FALL = {0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25}   # Fall / FallAerial / FallSpecial
AIRDODGE = 0xEC

STATE_GROUPS = [
    ("jump squat", {0x18}),
    ("jumping", {0x19, 0x1A, 0x1B, 0x1C}),
    ("aerial attack", set(range(0x41, 0x46))),
    ("landing lag (aerial)", set(range(0x46, 0x4B)) | {0x2A, 0x2B}),
    ("airdodge / wavedash", {AIRDODGE}),
    ("dash attack", {0x32}),
    ("ground attack (jab/tilt/smash)", set(range(0x2C, 0x32)) | set(range(0x33, 0x41))),
    ("dash / run", {0x14, 0x15, 0x16, 0x17}),
    ("turnaround", {0x12, 0x13}),
    ("crouch", SQUAT),
    ("shield", {0xB2, 0xB3}),
    ("shield drop", {0xB4}),
    ("shieldstun", {0xB5}),
    ("roll / spotdodge", {0xE9, 0xEA, 0xEB}),
    ("grab attempt", {0xD4, 0xD6}),
    ("standing / walking", {0x0E, 0x0F, 0x10, 0x11}),
    ("falling", FALL),
    ("on ledge / ledge option", LEDGE),
    ("getting up / on the ground", DOWN | TECH),
    ("special move", set(range(0x155, 0x200))),
    ("in hitstun already", DAMAGE),
]

ATTACKS = {2: "jab", 3: "jab", 4: "jab", 5: "rapid jab", 6: "dash attack", 7: "ftilt", 8: "utilt", 9: "dtilt",
           10: "fsmash", 11: "usmash", 12: "dsmash", 13: "nair", 14: "fair", 15: "bair", 16: "uair", 17: "dair",
           18: "neutral B", 19: "side B", 20: "up B", 21: "down B", 50: "getup attack", 51: "getup attack",
           52: "pummel", 53: "fthrow", 54: "bthrow", 55: "uthrow", 56: "dthrow", 61: "ledge attack", 62: "ledge attack"}
SPECIAL_NAMES = {  # per character, for the 4 specials (attack ids 18-21)
    "Fox": {18: "laser", 19: "illusion", 20: "firefox", 21: "shine"},
    "Falco": {18: "laser", 19: "phantasm", 20: "firebird", 21: "shine"},
    "Captain Falcon": {18: "falcon punch", 19: "raptor boost", 20: "falcon dive", 21: "falcon kick"},
    "Samus": {18: "charge shot", 19: "missile", 20: "screw attack", 21: "bomb"},
    "Jigglypuff": {18: "rollout", 19: "pound", 20: "sing", 21: "rest"},
}
BTN = {0x0010: "Z", 0x0020: "R", 0x0040: "L", 0x0100: "A", 0x0200: "B", 0x0400: "X", 0x0800: "Y"}


def state_group(a):
    for name, s in STATE_GROUPS:
        if a in s:
            return name
    return f"state {a:#x}"


def stick_region(x, y, dz=0.2875):
    return (0 if abs(x) < dz else (1 if x > 0 else -1), 0 if abs(y) < dz else (1 if y > 0 else -1))


def read_frames(path):
    with open(path, "rb") as f:
        d = f.read()
    gs, ge, last, last_frame, incomplete, meta = slippi_scan.read_events(d)
    raw = d[15:]
    psz = raw[1]
    sizes = {raw[2 + i]: struct.unpack(">H", raw[3 + i:5 + i])[0] for i in range(0, psz - 1, 3)}
    pos = 1 + psz
    post, pre = {}, {}
    while pos < len(raw):
        cmd = raw[pos]
        sz = sizes.get(cmd)
        if sz is None or pos + 1 + sz > len(raw):
            break
        b = raw[pos:pos + 1 + sz]
        if cmd == 0x38 and not b[6]:
            fr = struct.unpack(">i", b[1:5])[0]
            post.setdefault(b[5], {})[fr] = {
                "a": struct.unpack(">H", b[8:10])[0], "x": struct.unpack(">f", b[0xA:0xE])[0],
                "y": struct.unpack(">f", b[0xE:0x12])[0], "pct": struct.unpack(">f", b[0x16:0x1A])[0],
                "atk": b[0x1E], "stocks": b[0x21],
                "hitstun": struct.unpack(">f", b[0x2B:0x2F])[0] if sz >= 0x2E else 0.0,
                "air": b[0x2F] if sz >= 0x2F else 0, "lc": b[0x33] if sz >= 0x33 else 0}
        elif cmd == 0x37 and not b[6]:
            fr = struct.unpack(">i", b[1:5])[0]
            pre.setdefault(b[5], {})[fr] = {
                "jx": struct.unpack(">f", b[0x19:0x1D])[0], "jy": struct.unpack(">f", b[0x1D:0x21])[0],
                "cx": struct.unpack(">f", b[0x21:0x25])[0], "cy": struct.unpack(">f", b[0x25:0x29])[0],
                "btn": struct.unpack(">H", b[0x31:0x33])[0], "lt": struct.unpack(">f", b[0x33:0x37])[0],
                "rt": struct.unpack(">f", b[0x37:0x3B])[0]}
        pos += 1 + sz
    info = slippi_scan.scan_file(path)
    return info, post, pre


def analyze_game(path, me_port):
    info, post, pre = read_frames(path)
    ports = sorted(post)
    me = me_port - 1
    op = next(p for p in ports if p != me)
    chars = {p["port"] - 1: p["character"] for p in info["players"]}
    frames = sorted(set(post[me]) & set(post[op]))
    frames = [f for f in frames if f >= -123]
    EV = []  # situations with their frame, for clips: {type, p, frame, ...}
    P = {me: post[me], op: post[op]}

    # ---- conversions (Slippi-style)
    conv = {me: None, op: None}      # active conversion BY attacker (on the other)
    reset = {me: 0, op: 0}
    convs = []
    prev = {me: None, op: None}
    for f in frames:
        for att, vic in ((me, op), (op, me)):
            v, vp = P[vic][f], prev[vic]
            hurt = vp is not None and v["pct"] > vp["pct"] + 0.01
            grabbed = v["a"] in GRABBED and (vp is None or vp["a"] not in GRABBED)
            c = conv[att]
            if (hurt or grabbed) and c is None:
                other = conv[vic]
                kind = "neutral win"
                if other is not None:
                    kind = "trade" if other["start"] == f else "counter"
                c = conv[att] = {"att": att, "vic": vic, "start": f, "start_pct": vp["pct"] if vp else 0.0,
                                 "kind": kind, "moves": [], "kill": False, "end": f,
                                 "vic_state_before": state_group(P[vic][f - 1]["a"]) if f - 1 in P[vic] else "?",
                                 "vic_prev_states": [P[vic][g]["a"] for g in range(f - 20, f) if g in P[vic]]}
                convs.append(c)
                if other is not None and kind == "trade":
                    other["kind"] = "trade"
            if c is not None:
                if hurt:
                    c["moves"].append(P[att][f]["atk"])
                    c["end_pct"] = v["pct"]
                    c["end"] = f
                if vp is not None and v["stocks"] < vp["stocks"]:
                    c["kill"] = True
                    c["end_pct"] = vp["pct"]
                    c["end"] = f
                    conv[att] = None
                    continue
                free = not (v["a"] in DAMAGE or v["a"] in GRABBED or v["a"] in TECH or v["a"] in DOWN
                            or v["a"] in DEAD or v["a"] in SHIELD and v["a"] == 0xB5)
                reset[att] = reset[att] + 1 if free else 0
                if reset[att] > 45:
                    conv[att] = None
                    reset[att] = 0
        prev = {me: P[me][f], op: P[op][f]}
    for c in convs:
        c.setdefault("end_pct", c["start_pct"])
        c["damage"] = round(c["end_pct"] - c["start_pct"], 1)

    def side(att):
        return [c for c in convs if c["att"] == att]

    # ---- stocks / kills
    def stock_lost_frames(p):
        out, last = [], None
        for f in frames:
            s = P[p][f]["stocks"]
            if last is not None and s < last:
                out.append(f)
            last = s
        return out

    # ---- inputs per minute (button presses + stick/c-stick region changes)
    def apm(p, f0, f1):
        n, pb, pr, pc = 0, None, None, None
        for f in range(f0, f1):
            q = pre.get(p, {}).get(f)
            if q is None:
                continue
            b = q["btn"]
            if pb is not None:
                n += sum(1 for bit in BTN if b & bit and not pb & bit)
            r = stick_region(q["jx"], q["jy"])
            c = stick_region(q["cx"], q["cy"])
            if pr is not None and r != pr and r != (0, 0):
                n += 1
            if pc is not None and c != pc and c != (0, 0):
                n += 1
            pb, pr, pc = b, r, c
        mins = max(1, f1 - f0) / 3600
        return round(n / mins)

    # stock segments for ME: pace per stock (from game start/respawn to that stock's loss)
    my_losses = stock_lost_frames(me)
    op_losses = stock_lost_frames(op)
    bounds = [frames[0]] + my_losses + [frames[-1]]
    pace = []
    for i in range(len(bounds) - 1):
        f0, f1 = bounds[i], bounds[i + 1]
        pace.append({"stock": i + 1, "seconds": round((f1 - f0) / 60, 1), "my_apm": apm(me, f0, f1),
                     "op_apm": apm(op, f0, f1)})

    # re-engage after respawn: frames from end of my Rebirth states to the next conversion (either side)
    reengage = []
    for lf in my_losses:
        out = next((f for f in frames if f > lf and P[me][f]["a"] not in REBIRTH and P[me][f]["a"] not in DEAD), None)
        if out is None:
            continue
        nxt = next((c for c in convs if c["start"] > out), None)
        if nxt:
            reengage.append({"after_stock_loss_s": round((nxt["start"] - out) / 60, 1),
                             "who_opened": "me" if nxt["att"] == me else "opponent", "kind": nxt["kind"]})

    # ---- grabs
    def grabs(p):
        tries = hits = 0
        prev_a = None
        for f in frames:
            a = P[p][f]["a"]
            if a in GRAB_START and prev_a not in GRAB_START:
                tries += 1
                if any(P[p].get(g, {}).get("a") in GRAB_HOLD for g in range(f, f + 40)):
                    hits += 1
            prev_a = a
        return tries, hits

    # ---- tech situations of the OTHER player and my follow-up
    def tech_chase(chaser, teched):
        out = []
        prev_a = None
        for f in frames:
            a = P[teched][f]["a"]
            if (a in TECH_NAMES or a in MISSED_TECH) and a != prev_a and prev_a not in TECH and prev_a not in DOWN:
                follow = None
                for g in range(f, f + 75):
                    if g not in P[teched]:
                        break
                    prv = P[teched].get(g - 1)
                    if prv and (P[teched][g]["pct"] > prv["pct"] + 0.01 or
                                (P[teched][g]["a"] in GRABBED and prv["a"] not in GRABBED)):
                        follow = "grab" if P[teched][g]["a"] in GRABBED else ATTACKS.get(P[chaser][g]["atk"], "hit")
                        break
                out.append({"option": TECH_NAMES.get(a, "missed tech"), "followed_up": follow})
                EV.append({"type": "tech_chase", "p": chaser, "frame": f, "option": TECH_NAMES.get(a, "missed tech"),
                           "followed_up": follow})
            prev_a = a
        return out

    # ---- crouch -> dash/turn (dashback out of crouch) and crouch outcomes
    def crouch(p):
        squats = dashback = cc_hit = 0
        prev_a = None
        for f in frames:
            a = P[p][f]["a"]
            if a in SQUAT and prev_a not in SQUAT:
                squats += 1
                g = f
                while g in P[p] and P[p][g]["a"] in SQUAT and g < f + 240:
                    g += 1
                q = P[p].get(g)
                if q is not None and q["a"] in DAMAGE:
                    cc_hit += 1
                    EV.append({"type": "crouch_hit", "p": p, "frame": f, "hit_at": g})
                # out of crouch: a dash/turn within 6 frames, passing only through standing
                for h in range(g, g + 7):
                    s = P[p].get(h, {}).get("a")
                    if s in (DASH, TURN):
                        dashback += 1
                        EV.append({"type": "crouch_dash", "p": p, "frame": f, "dash_at": h})
                        break
                    if s not in (0x0E, 0x0F):
                        break
            prev_a = a
        return {"crouches": squats, "dash_out_of_crouch": dashback, "hit_while_crouching": cc_hit}

    # ---- what I did right after hitstun ended (in the air), and was I hit again soon
    def after_hitstun(p, other):
        out = []
        prev = None
        for f in frames:
            q = P[p][f]
            if prev is not None and prev["a"] in DAMAGE and prev["hitstun"] > 0 and q["hitstun"] <= 0 and q["air"]:
                choice = "nothing (drifted / fell)"
                for g in range(f, f + 20):
                    a = P[p].get(g, {}).get("a")
                    if a is None:
                        break
                    if a in (0x1B, 0x1C):
                        choice = "double jump"
                        break
                    if a == AIRDODGE:
                        choice = "airdodge"
                        break
                    if 0x41 <= a <= 0x45:
                        choice = "aerial"
                        break
                    if a >= 0x155:
                        choice = "special (up B etc.)"
                        break
                    if a in DAMAGE and g > f and P[p][g]["pct"] > P[p][g - 1]["pct"]:
                        break
                rehit = any(P[p].get(g) and P[p].get(g - 1) and P[p][g]["pct"] > P[p][g - 1]["pct"] + 0.01
                            for g in range(f + 1, f + 45))
                out.append({"choice": choice, "hit_again_within_0.75s": rehit, "pct": round(q["pct"])})
            prev = q
        return out

    def opened_at(victim):
        return [c["start"] for c in convs if c["vic"] == victim]

    # ---- my aerials: hit / shielded / whiffed, and was I opened before I could act again (~40 frames)
    def aerials(p, other):
        out = {"thrown": 0, "hit": 0, "shielded": 0, "whiffed": 0, "punished": 0, "whiffed_and_punished": 0,
               "shielded_and_punished": 0}
        opened = set(opened_at(p))
        prev_a = None
        for f in frames:
            a = P[p][f]["a"]
            if 0x41 <= a <= 0x45 and not (prev_a is not None and 0x41 <= prev_a <= 0x45):
                out["thrown"] += 1
                res = "whiffed"
                for g in range(f, f + 30):
                    q, qp = P[other].get(g), P[other].get(g - 1)
                    if q is None or qp is None:
                        break
                    if q["pct"] > qp["pct"] + 0.01:
                        res = "hit"
                        break
                    if q["a"] == 0xB5 and qp["a"] != 0xB5:
                        res = "shielded"
                        break
                out[res] += 1
                pun = any(g in opened for g in range(f, f + 40)) and res != "hit"
                EV.append({"type": "aerial", "p": p, "frame": f, "move": a, "result": res, "punished": pun})
                if pun:
                    out["punished"] += 1
                    if res in ("whiffed", "shielded"):
                        out[f"{res}_and_punished"] += 1
            prev_a = a
        return out

    # ---- opponent crouching near me: what I did next (within 30 frames) and the result
    def vs_crouch(p, other):
        out = {}
        prev_a = None
        last_f = -999
        opened_me, opened_them = set(opened_at(p)), set(opened_at(other))
        for f in frames:
            a = P[other][f]["a"]
            near = abs(P[other][f]["x"] - P[p][f]["x"]) < 35 and abs(P[other][f]["y"] - P[p][f]["y"]) < 20
            if a in SQUAT and prev_a not in SQUAT and near and f - last_f > 30:
                last_f = f
                choice = "waited / nothing committal"
                for g in range(f, f + 30):
                    m = P[p].get(g, {}).get("a")
                    if m is None:
                        break
                    if m in GRAB_START:
                        choice = "grab"
                        break
                    if 0x41 <= m <= 0x45 or m == 0x18:
                        choice = "jump / aerial"
                        break
                    if 0x2C <= m <= 0x40:
                        choice = "ground attack"
                        break
                    if m >= 0x155:
                        choice = "special move"
                        break
                    if m in (DASH, TURN) and g > f + 2:
                        choice = "dash away / reposition"
                        break
                win = "I got hit" if any(g in opened_me for g in range(f, f + 60)) else (
                    "I opened them" if any(g in opened_them for g in range(f, f + 60)) else "neutral reset")
                out.setdefault(choice, {}).setdefault(win, 0)
                out[choice][win] += 1
                EV.append({"type": "vs_crouch", "p": p, "frame": f, "choice": choice, "result": win})
            prev_a = a
        return out

    # ---- opponent shielding near me: did I grab?
    def vs_shield(p, other):
        n = grabbed = 0
        prev_a = None
        for f in frames:
            a = P[other][f]["a"]
            if a in (0xB2, 0xB5) and prev_a not in SHIELD and abs(P[other][f]["x"] - P[p][f]["x"]) < 35:
                n += 1
                gr = any(P[p].get(g, {}).get("a") in GRAB_START for g in range(f, f + 30))
                grabbed += gr
                om, ot = set(opened_at(p)), set(opened_at(other))
                res = "I got hit" if any(g in om for g in range(f, f + 60)) else (
                    "I opened them" if any(g in ot for g in range(f, f + 60)) else "neutral reset")
                EV.append({"type": "vs_shield", "p": p, "frame": f, "grabbed": gr, "result": res})
            prev_a = a
        return {"opponent_shielded_near_me": n, "i_grabbed_within_0.5s": grabbed}

    def actionable_apm(p):
        n, pb, pr, pc, fr = 0, None, None, None, 0
        for f in frames:
            st = P[p][f]["a"]
            if st in DAMAGE or st in GRABBED or st in DEAD or st in REBIRTH:
                pb = pr = pc = None
                continue
            q = pre.get(p, {}).get(f)
            if q is None:
                continue
            fr += 1
            b = q["btn"]
            r, c = stick_region(q["jx"], q["jy"]), stick_region(q["cx"], q["cy"])
            if pb is not None:
                n += sum(1 for bit in BTN if b & bit and not pb & bit)
                n += (r != pr and r != (0, 0)) + (c != pc and c != (0, 0))
            pb, pr, pc = b, r, c
        return round(n / max(1, fr) * 3600)

    def lcancel(p):
        ok = sum(1 for f in frames if P[p][f]["lc"] == 1)
        bad = sum(1 for f in frames if P[p][f]["lc"] == 2)
        return ok, bad

    def summary(att):
        cs = side(att)
        ow = [c for c in cs if c["kind"] == "neutral win"]
        kills = [c for c in cs if c["kill"]]
        dmg = sum(c["damage"] for c in cs)
        name = chars[att]
        mv = lambda i: SPECIAL_NAMES.get(name, {}).get(i) or ATTACKS.get(i, f"move {i}")
        opener = {}
        for c in ow:
            k = mv(c["moves"][0]) if c["moves"] else "grab"
            opener[k] = opener.get(k, 0) + 1
        killers = {}
        for c in kills:
            k = mv(c["moves"][-1]) if c["moves"] else "?"
            killers[k] = killers.get(k, 0) + 1
        vic_state = {}
        for c in cs:
            vic_state[c["vic_state_before"]] = vic_state.get(c["vic_state_before"], 0) + 1
        return {"character": name, "openings": len(cs), "neutral_wins": len(ow),
                "counter_hits": sum(1 for c in cs if c["kind"] == "counter"),
                "trades": sum(1 for c in cs if c["kind"] == "trade"),
                "kills": len(kills), "total_damage": round(dmg, 1),
                "damage_per_opening": round(dmg / len(cs), 1) if cs else 0,
                "openings_per_kill": round(len(cs) / len(kills), 1) if kills else None,
                "neutral_openers": dict(sorted(opener.items(), key=lambda x: -x[1])),
                "kill_moves": killers,
                "victim_was_doing": dict(sorted(vic_state.items(), key=lambda x: -x[1])),
                "kill_percents": [round(c["end_pct"]) for c in kills]}

    g_me, g_op = grabs(me), grabs(op)
    lc_me, lc_op = lcancel(me), lcancel(op)
    return {
        "file": os.path.basename(path), "stage": info["stage"], "seconds": round(len(frames) / 60, 1),
        "winner": "me" if info["winner_port"] == me + 1 else "opponent",
        "me": {**summary(me), "grabs": {"tries": g_me[0], "landed": g_me[1]},
               "lcancel": {"ok": lc_me[0], "missed": lc_me[1]}, "crouch": crouch(me),
               "tech_chases_on_opponent": tech_chase(me, op), "after_hitstun": after_hitstun(me, op),
               "my_techs": tech_chase(op, me), "aerials": aerials(me, op), "vs_their_crouch": vs_crouch(me, op),
               "vs_their_shield": vs_shield(me, op), "actionable_apm": actionable_apm(me),
               "stocks_taken": 4 - P[op][frames[-1]]["stocks"]},
        "op": {**summary(op), "grabs": {"tries": g_op[0], "landed": g_op[1]},
               "lcancel": {"ok": lc_op[0], "missed": lc_op[1]}, "crouch": crouch(op),
               "after_hitstun": after_hitstun(op, me), "aerials": aerials(op, me),
               "vs_their_crouch": vs_crouch(op, me), "actionable_apm": actionable_apm(op),
               "stocks_taken": 4 - P[me][frames[-1]]["stocks"]},
        "pace_per_my_stock": pace, "reengage_after_my_stock_loss": reengage,
        "timeline": [{"t": round((c["start"] + 123) / 60, 1), "who": "me" if c["att"] == me else "op",
                      "kind": c["kind"], "damage": c["damage"], "kill": c["kill"]} for c in convs],
        "events": [{**e, "who": "me" if e["p"] == me else "op", "t": round((e["frame"] + 123) / 60, 2)}
                   for e in EV],
        "my_stock_losses_t": [round((f + 123) / 60, 1) for f in my_losses],
        "op_stock_losses_t": [round((f + 123) / 60, 1) for f in op_losses],
        "end_stocks": {"me": P[me][frames[-1]]["stocks"], "op": P[op][frames[-1]]["stocks"]},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int, help="my port (1-4)")
    ap.add_argument("games", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    res = [analyze_game(g, a.port) for g in a.games]
    print(json.dumps(res, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
