#!/usr/bin/env python3
"""
slp_repair.py - write a repaired COPY of a .slp whose event data has a few flipped bits.

Usage:
    python tools\\python\\slp_repair.py "<damaged.slp>" "<repaired copy.slp>"

The original is only read (replays are read-only). Built for PROTOCOL #57 set T game 3
(Hyraks setup, Game_002147B26B02_20170510T180503.slp): ~2.7 KB in the middle had single-bit
flips (command 0x38 -> 0x78, frame 14482 -> 14486, nana 0 -> 128), so Dolphin refused the
file and the scanner stopped there. Event sizes were intact, so every event is still at the
right offset.

How: walk the events; whenever a byte doesn't parse, or an event's frame number / port /
nana field doesn't fit the frame being read, set it back:
  - command byte: the valid event command one bit-flip away that lets the walk continue
  - frame number: the current frame (from the frame-start event 0x3a, or the previous + 1)
  - port: one of the game's player ports (from Game Start); nana: 0 (no Ice Climbers)
Event payloads (inputs, positions) can't be checked this way; Slippi playback re-applies
positions each frame, so a stray bit there doesn't carry forward. Prints every change.
"""
import struct
import sys

FRAME_EVENTS = (0x37, 0x38, 0x3a, 0x3b, 0x3c)  # pre-frame, post-frame, frame start, item, frame end


def repair(src, dst):
    d = bytearray(open(src, "rb").read())
    if d[:11] != b"{U\x03raw[$U#l":
        raise SystemExit("not a .slp file")
    rawlen = struct.unpack(">I", d[11:15])[0]
    base = 15
    raw_end = base + rawlen
    n = d[base + 1]
    sizes = {d[base + 2 + i * 3]: struct.unpack(">H", d[base + 3 + i * 3:base + 5 + i * 3])[0] for i in range(n // 3)}
    pos = base + 1 + n
    gs_size = sizes[0x36]
    # player ports in use from Game Start: player block i at 0x65 + 0x24*i, type byte +1 (3 = empty)
    gs = d[pos:pos + 1 + gs_size]
    ports = {i for i in range(4) if gs[0x65 + 0x24 * i + 1] != 3}
    changes = []

    def parses_from(p, depth=2):
        for _ in range(depth):
            if p >= raw_end:
                return True
            c = d[p]
            if c not in sizes:
                return False
            p += 1 + sizes[c]
        return True

    # Ice Climbers add Nana events, which this fixed per-frame layout doesn't model.
    if any(gs[0x65 + 0x24 * i] == 0x0E for i in ports):
        raise SystemExit("Ice Climbers in this game: not supported, nothing written")
    order = sorted(ports)
    P = len(order)

    def allowed(state):
        """Event types that may come next. Each frame is: 0x3a frame start, one 0x37 per
        player (port order), any 0x3b items, one 0x38 per player, 0x3c frame end."""
        kind, k = state
        if kind in ("start", "3c"):
            return {0x3a} | ({c for c in sizes if c not in FRAME_EVENTS})  # 0x10/0x39/... between frames
        if kind == "3a":
            return {0x37}
        if kind == "37":
            return {0x37} if k < P else {0x3b, 0x38}
        if kind == "3b":
            return {0x3b, 0x38}
        if kind == "38":
            return {0x38} if k < P else {0x3c}
        return set(sizes)

    frame, state = None, ("start", 0)
    while pos < raw_end:
        c = d[pos]
        ok = allowed(state) if frame is not None else set(sizes)
        if c not in ok:
            # nearest allowed command by flipped bits that keeps the stream parsing
            cands = sorted((bin(c ^ x).count("1"), x) for x in ok)
            fixed = None
            for _, cand in cands:
                d[pos] = cand
                if parses_from(pos):
                    fixed = cand
                    break
            d[pos] = c
            if fixed is None:
                raise SystemExit(f"can't repair byte {pos - base} (0x{c:02x}); stopping, nothing written")
            d[pos] = fixed
            changes.append(f"byte {pos - base}: command 0x{c:02x} -> 0x{fixed:02x}")
            c = fixed
        if c in FRAME_EVENTS:
            f = struct.unpack(">i", d[pos + 1:pos + 5])[0]
            if frame is None:
                want = f
            else:
                want = frame + 1 if c == 0x3a else frame
            if f != want:
                d[pos + 1:pos + 5] = struct.pack(">i", want)
                changes.append(f"byte {pos - base}: event 0x{c:02x} frame {f} -> {want}")
            if c == 0x3a:
                frame = want
            if c in (0x37, 0x38):
                k = state[1] if state[0] == ("37" if c == 0x37 else "38") else 0
                port, nana = d[pos + 5], d[pos + 6]
                if port != order[k]:
                    d[pos + 5] = order[k]
                    changes.append(f"byte {pos - base}: event 0x{c:02x} port {port} -> {order[k]}")
                if nana != 0:
                    d[pos + 6] = 0
                    changes.append(f"byte {pos - base}: event 0x{c:02x} nana {nana} -> 0")
        # advance the per-frame state
        name = {0x3a: "3a", 0x37: "37", 0x38: "38", 0x3b: "3b", 0x3c: "3c"}.get(c)
        if name in ("37", "38"):
            state = (name, state[1] + 1 if state[0] == name else 1)
        elif name:
            state = (name, 0)
        pos += 1 + sizes[c]
    changes += repair_payload(d, base, raw_end, sizes, changes)
    with open(dst, "wb") as f:
        f.write(d)
    return changes


# Field offsets inside an event (byte 0 = command).
PRE = {"seed": (0x07, ">I"), "act": (0x0B, ">H"), "x": (0x0D, ">f"), "y": (0x11, ">f"), "face": (0x15, ">f"),
       "jx": (0x19, ">f"), "jy": (0x1D, ">f"), "cx": (0x21, ">f"), "cy": (0x25, ">f"), "trig": (0x29, ">f"),
       "pct": (0x3C, ">f")}
POST = {"char": (0x07, ">B"), "act": (0x08, ">H"), "x": (0x0A, ">f"), "y": (0x0E, ">f"), "face": (0x12, ">f"),
        "pct": (0x16, ">f"), "shield": (0x1A, ">f"), "stocks": (0x21, ">B")}


def bits(a, b, fmt):
    n = struct.calcsize(fmt)
    x, y = struct.unpack(f">{'BHIQ'[[1, 2, 4, 8].index(n)]}", struct.pack(fmt, a)), \
        struct.unpack(f">{'BHIQ'[[1, 2, 4, 8].index(n)]}", struct.pack(fmt, b))
    return bin(x[0] ^ y[0]).count("1")


def lcg_reach(a, b, limit=5000):
    """Is RNG seed b reachable from a in at most `limit` Melee RNG steps?"""
    s = a
    for _ in range(limit + 1):
        if s == b:
            return True
        s = (s * 214013 + 2531011) & 0xFFFFFFFF
    return False


def repair_payload(d, base, raw_end, sizes, struct_changes):
    """Second pass, only on frames near the structural damage: game values with flipped bits.
    Each frame's pre-frame x/y/facing/action normally equals the previous frame's post-frame
    values (99.8% on clean #57 files), so a disagreeing pair is two readings of one value: keep
    the one that fits the neighbouring frames. Character id per port is constant (except
    Zelda/Sheik), facing is +-1, stick values are in -1..1, RNG seeds follow Melee's LCG."""
    import re
    import math
    hit = sorted(int(m.group(1)) for c in struct_changes for m in [re.match(r"byte (\d+):", c)] if m)
    ev = {}  # (kind, frame, port) -> absolute offset of the event
    pos = base + 1 + d[base + 1]
    frame_at = []  # (offset, frame)
    while pos < raw_end:
        c = d[pos]
        if c in (0x37, 0x38):
            f = struct.unpack(">i", d[pos + 1:pos + 5])[0]
            ev[("pre" if c == 0x37 else "post", f, d[pos + 5])] = pos
            frame_at.append((pos - base, f))
        pos += 1 + sizes[c]
    if not hit:
        return []
    import bisect
    offs = [o for o, _ in frame_at]
    fr_of = lambda o: frame_at[max(0, bisect.bisect_right(offs, o) - 1)][1]
    lo, hi = fr_of(hit[0]) - 3, fr_of(hit[-1]) + 3
    ports = sorted({p for (_, _, p) in ev})
    out = []

    def get(kind, f, p, field):
        o = ev.get((kind, f, p))
        if o is None:
            return None
        off, fmt = (PRE if kind == "pre" else POST)[field]
        return struct.unpack(fmt, d[o + off:o + off + struct.calcsize(fmt)])[0]

    def put(kind, f, p, field, val):
        o = ev[(kind, f, p)]
        off, fmt = (PRE if kind == "pre" else POST)[field]
        old = get(kind, f, p, field)
        if old == val or (isinstance(old, float) and isinstance(val, float) and struct.pack(fmt, old) == struct.pack(fmt, val)):
            return
        d[o + off:o + off + struct.calcsize(fmt)] = struct.pack(fmt, val)
        out.append(f"frame {f} port {p} {kind} {field}: {old!r} -> {val!r}")

    def good_float(v, lim=1e4):
        return v is not None and math.isfinite(v) and abs(v) < lim

    for p in ports:
        # character id: most common value just outside the window
        chars = [get("post", f, p, "char") for f in list(range(lo - 60, lo)) + list(range(hi + 1, hi + 61))]
        chars = [c for c in chars if c is not None]
        main = max(set(chars), key=chars.count) if chars else None
        for f in range(lo, hi + 1):
            if main is not None and get("post", f, p, "char") not in (main, None):
                # Zelda (19) <-> Sheik (7) transform is real; anything else in the window is a flip
                if {get("post", f, p, "char"), main} != {7, 19}:
                    put("post", f, p, "char", main)
        # boundary values: post(f-1) and pre(f) should agree
        for field in ("x", "y", "face", "act"):
            for f in range(lo, hi + 1):
                a, b = get("post", f - 1, p, field), get("pre", f, p, field)
                if a is None or b is None or a == b:
                    continue
                # Facing and action really do change between frames (turns, new moves: ~3% of
                # frames on clean files), so only impossible values count as flips there.
                if field == "face":
                    ok = [v for v in (a, b) if v in (1.0, -1.0)]
                    if len(ok) == 2:
                        continue
                    pick = ok[0] if ok else (get("post", f, p, "face") if get("post", f, p, "face") in (1.0, -1.0) else 1.0)
                elif field == "act":
                    valid = [v for v in (a, b) if v < 0x200]
                    if len(valid) != 1:
                        continue
                    pick = valid[0]
                else:
                    # prediction from the nearest boundaries where both readings agree and look sane
                    def anchor(step):
                        g = f + step
                        while lo - 10 <= g <= hi + 10:
                            x1, x2 = get("post", g - 1, p, field), get("pre", g, p, field)
                            if x1 is not None and x1 == x2 and good_float(x1):
                                return g, x1
                            g += step
                        return None
                    A, B = anchor(-1), anchor(+1)
                    if A and B:
                        pred = A[1] + (B[1] - A[1]) * (f - A[0]) / (B[0] - A[0])
                    else:
                        pred = (A or B)[1] if (A or B) else 0.0
                    pick = min((v for v in (a, b) if good_float(v)), key=lambda v: abs(v - pred), default=pred)
                put("post", f - 1, p, field, pick)
                put("pre", f, p, field, pick)
        # post-only values: a lone outlier between two equal neighbours is a flip
        for field in ("pct", "shield", "stocks"):
            for f in range(lo, hi + 1):
                v0, v, v1 = get("post", f - 1, p, field), get("post", f, p, field), get("post", f + 1, p, field)
                if v0 is not None and v0 == v1 and v != v0:
                    put("post", f, p, field, v0)
        for f in range(lo, hi + 1):
            v0, v, v1 = get("pre", f - 1, p, "pct"), get("pre", f, p, "pct"), get("pre", f + 1, p, "pct")
            if v0 is not None and v0 == v1 and v != v0:
                put("pre", f, p, "pct", v0)
        # stick / trigger values must be real numbers in range; else keep the previous frame's
        for field, lim in (("jx", 1.0), ("jy", 1.0), ("cx", 1.0), ("cy", 1.0), ("trig", 1.0)):
            for f in range(lo, hi + 1):
                v = get("pre", f, p, field)
                if v is not None and not (math.isfinite(v) and abs(v) <= lim + 1e-6):
                    put("pre", f, p, field, get("pre", f - 1, p, field))
        # RNG seed: must follow from the previous frame's; else the single-bit flip that does
        for f in range(lo, hi + 1):
            s0, s, s1 = get("pre", f - 1, p, "seed"), get("pre", f, p, "seed"), get("pre", f + 1, p, "seed")
            if None in (s0, s) or lcg_reach(s0, s):
                continue
            for bit in range(32):
                cand = s ^ (1 << bit)
                if lcg_reach(s0, cand) and (s1 is None or lcg_reach(cand, s1)):
                    put("pre", f, p, "seed", cand)
                    break
            else:
                out.append(f"frame {f} port {p} pre seed {s:08x}: not reachable, left as is")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    if sys.argv[1] == sys.argv[2]:
        raise SystemExit("write the repair to a different file; replays are read-only")
    ch = repair(sys.argv[1], sys.argv[2])
    print(f"{len(ch)} change(s):")
    for c in ch:
        print("  " + c)
