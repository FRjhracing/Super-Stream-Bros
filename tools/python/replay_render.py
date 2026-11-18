#!/usr/bin/env python3
"""
replay_render.py - render a Slippi replay (.slp) to an .mp4 with the playback Dolphin.

Usage:
    python tools\\python\\replay_render.py "<game.slp>" "<out.mp4>" [--iso <melee 1.02 iso>]

Uses a private copy of Slippi's playback Dolphin in tools\\render\\slippi_playback\\
(portable, with frame + audio dumping turned on), so the Slippi Launcher's own
playback settings are never touched. The replay is read only.

How: write a Slippi "comm" file, start Dolphin with it, read its --cout output
([CURRENT_FRAME] n), close Dolphin once the replay's last frame has played
(Dolphin reports PLAYBACK_END_FRAME as "infinite" in normal mode, so the last
frame is read from the .slp itself), then mux Dump\\Frames\\framedump*.avi +
Dump\\Audio\\dspdump.wav, trimmed to the game. (dtkdump.wav is silent for Melee.)
Dolphin runs at normal speed and dumps from frame -123, so video time t is
replay frame -123 + 60*t.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

CODE = os.path.dirname(os.path.abspath(__file__))           # tools\\python (the scripts)
ROOT = os.path.dirname(os.path.dirname(CODE))                # project folder
HERE = ROOT  # older name, kept for compatibility
DOLPHIN_DIR = os.path.join(ROOT, "tools", "render", "slippi_playback")
DOLPHIN = os.path.join(DOLPHIN_DIR, "Slippi Dolphin.exe")
DUMP = os.path.join(DOLPHIN_DIR, "User", "Dump")
FFMPEG = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffmpeg.exe")
FFPROBE = os.path.join(ROOT, "tools", "ffmpeg", "bin", "ffprobe.exe")
MACHINES = os.path.join(ROOT, "machine_settings.json")
LAPTOP_ISO = os.path.join(os.path.expanduser("~"), "Documents", "Game", "Melee", "vanilla", "game.iso")  # optional fallback location
TAIL_FRAMES = 90  # keep 1.5 s after the last frame
STALL_S = 12  # frame counter frozen this long = playback finished
STUCK_S = 60  # frozen this long before the end = Dolphin paused/stuck (e.g. clicked or lost focus)


def machine_settings():
    """This PC's entry in machine_settings.json, keyed by computer name, so the
    project folder can be copied between the laptop and the desktop unchanged."""
    try:
        with open(MACHINES, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data.get(os.environ.get("COMPUTERNAME", ""), {})


def default_iso():
    """machine_settings.json "iso", then %USERPROFILE%\\Documents\\Game\\Melee\\vanilla\\game.iso, then the Slippi Launcher's ISO."""
    cands = [machine_settings().get("iso"), LAPTOP_ISO]
    try:
        with open(os.path.join(os.environ.get("APPDATA", ""), "Slippi Launcher", "Settings"), encoding="utf-8") as f:
            cands.append(json.load(f)["settings"]["isoPath"])
    except (OSError, ValueError, KeyError):
        pass
    for c in cands:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError("No Melee 1.02 ISO found: set \"iso\" for this PC in machine_settings.json")


def default_speed():
    return float(machine_settings().get("render_speed", 0.85))


def count_frames(avi):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_packets",
                          "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", avi],
                         capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else 0


def last_frame_of(slp):
    sys.path.insert(0, CODE)
    import slippi_scan
    with open(slp, "rb") as f:
        _, _, _, last, _, _ = slippi_scan.read_events(f.read())
    return last


def clear_dumps():
    for sub in ("Frames", "Audio"):
        d = os.path.join(DUMP, sub)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))


def set_speed(speed):
    """Emulation speed in the private Dolphin.ini. Below 1.0 gives the laptop's iGPU
    headroom so no frames are skipped; dumps follow emulated time, not wall time."""
    p = os.path.join(DOLPHIN_DIR, "User", "Config", "Dolphin.ini")
    with open(p, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"(?m)^EmulationSpeed\s*=.*$", f"EmulationSpeed = {speed:.8f}", text)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def render(slp, out, iso=None, speed=None, timeout_s=1800, log=print):
    iso = iso or default_iso()
    speed = default_speed() if speed is None else speed
    slp = os.path.abspath(slp)
    if not os.path.isfile(slp):
        raise FileNotFoundError(slp)
    last = last_frame_of(slp)
    if last is None:
        raise RuntimeError("replay has no frame data")
    set_speed(speed)
    clear_dumps()
    comm = {"mode": "normal", "replay": slp, "isRealTimeMode": False,
            "outputOverlayFiles": False, "commandId": uuid.uuid4().hex}
    tmp = tempfile.mkdtemp(prefix="slprender_")
    comm_path = os.path.join(tmp, "comm.json")
    with open(comm_path, "w", encoding="utf-8") as f:
        json.dump(comm, f)

    proc = subprocess.Popen([DOLPHIN, "-i", comm_path, "-b", "-e", iso, "--cout"],
                            cwd=DOLPHIN_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    state = {"cur": None, "end": None, "game_end": None}

    def reader():
        for line in proc.stdout:
            m = re.match(r"\[(CURRENT_FRAME|PLAYBACK_END_FRAME|GAME_END_FRAME)\]\s+(-?\d+)", line.strip())
            if m:
                key = {"CURRENT_FRAME": "cur", "PLAYBACK_END_FRAME": "end", "GAME_END_FRAME": "game_end"}[m.group(1)]
                state[key] = int(m.group(2))
    threading.Thread(target=reader, daemon=True).start()

    t0, last_print = time.time(), 0
    seen, seen_at = None, time.time()
    first_at = done_at = None
    try:
        while proc.poll() is None:
            time.sleep(0.25)
            cur = state["cur"]
            if cur != seen:
                seen, seen_at = cur, time.time()
                if first_at is None:
                    first_at = time.time()  # boot + replay load done, playback running
                if done_at is None and cur >= last:
                    done_at = time.time()
            if time.time() - last_print > 15 and cur is not None:
                log(f"    frame {cur}/{last}")
                last_print = time.time()
            if cur is not None and cur >= last + TAIL_FRAMES:
                break
            if cur is not None and cur >= last - 5 and time.time() - seen_at > STALL_S:
                break  # replay ended and Dolphin is holding the last frame
            if cur is not None and cur < last - 5 and time.time() - seen_at > STUCK_S:
                raise RuntimeError(f"playback stuck at frame {cur} of {last} for {STUCK_S} s "
                                   "(Dolphin window clicked, paused or lost focus?); re-run to retry this game")
            if time.time() - t0 > timeout_s:
                raise TimeoutError(f"render took over {timeout_s}s (frame {cur}/{last})")
        if proc.poll() is not None and (state["cur"] or -999) < last - 5:
            raise RuntimeError(f"Dolphin closed early at frame {state['cur']} of {last} (was the window closed?)")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    time.sleep(1)  # let Dolphin finish closing the dump files

    videos = sorted(glob.glob(os.path.join(DUMP, "Frames", "framedump*.avi")))
    audio = os.path.join(DUMP, "Audio", "dspdump.wav")
    if not videos:
        raise RuntimeError("Dolphin produced no frame dump (check tools\\render\\slippi_playback\\User\\Config).")
    # Dropped-frame check: the dump should hold one frame per emulated frame from -123 on.
    # Too fast a speed for the PC makes the dump come up short (game clock runs ahead of the video).
    dumped = sum(count_frames(v) for v in videos)
    played = (state["cur"] or 0) + 124
    ratio = dumped / played if played > 0 else 0
    # Only a short dump is a sure sign: the dump also holds the ~12 s wait after the last frame
    # (STALL_S), so small drops can hide behind it. Check the in-game timer when trying a new speed.
    if ratio < 1.0:
        log(f"    WARNING: dump has {dumped} frames for {played} played ({ratio:.1%}) at speed {speed}: "
            f"frames were dropped, lower render_speed in machine_settings.json and re-render this game")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    # Several framedump files appear if the resolution changed mid-dump: concatenate them.
    args = [FFMPEG, "-v", "error", "-y"]
    for v in videos:
        args += ["-i", v]
    has_audio = os.path.isfile(audio) and os.path.getsize(audio) > 1000
    if has_audio:
        args += ["-i", audio]
    if len(videos) > 1:
        fc = "".join(f"[{i}:v]scale=1280:1056,setsar=1[v{i}];" for i in range(len(videos)))
        fc += "".join(f"[v{i}]" for i in range(len(videos))) + f"concat=n={len(videos)}:v=1:a=0[v]"
        args += ["-filter_complex", fc, "-map", "[v]"]
    else:
        args += ["-map", "0:v"]
    if has_audio:
        args += ["-map", f"{len(videos)}:a", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    length_s = (last + 123 + TAIL_FRAMES) / 60
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", "60",
             "-t", f"{length_s:.3f}", out]
    subprocess.run(args, check=True)
    return {"last_frame": last, "length_s": round(length_s, 2), "video_parts": len(videos), "audio": has_audio,
            "frames_dumped": dumped, "frames_played": played, "wall_s": round(time.time() - t0, 1), "speed": speed,
            "startup_s": round(first_at - t0, 1) if first_at else None,
            "playback_s": round(done_at - first_at, 1) if first_at and done_at else None}


def main():
    ap = argparse.ArgumentParser(description="Render a Slippi replay to mp4.")
    ap.add_argument("slp")
    ap.add_argument("out")
    ap.add_argument("--iso", default=None, help="Melee 1.02 ISO (default: machine_settings.json, then auto)")
    ap.add_argument("--speed", type=float, default=None,
                    help="emulation speed while dumping (default: render_speed for this PC in "
                         "machine_settings.json, else 0.85; 1.0 drops ~5%% of frames on the laptop)")
    a = ap.parse_args()
    info = render(a.slp, a.out, a.iso, a.speed)
    print(f"done: {a.out} {info}")


if __name__ == "__main__":
    sys.exit(main())
