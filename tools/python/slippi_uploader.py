#!/usr/bin/env python3
"""
Slippi flash-drive auto-uploader.

Run it at the start of a tournament night:
    python tools\\python\\slippi_uploader.py "Protocol #54"

Plug in a flash drive. The script will:
  1. Read the drive's name (no drive letter) and suggest it as the folder name.
     Press Enter to accept it, or type a different name.
  2. Remember that choice (slippi_uploader_config.json) so the same drive is
     pre-filled next time.
  3. Copy the .slp files to the external SSD "Project Storage":
         <SSD>\\Protocol VOD\\Melee\\<tournament>\\replays\\<folder name>\\
     (the local replay folder the VOD cutter uses), then say the drive can be pulled.
  4. Upload that SSD copy to Google Drive  gdrive:<tournament>/<folder name>/  in the
     background while you plug in the next drive (log: replays\\upload_<folder>.log).
  5. When you finish (q / Ctrl+C), wait for the uploads, offer a retry for any that
     failed, and print a summary.
Without the SSD it uploads straight from the drive to Google Drive, as before.

If a drive has a "Slippi" folder at its root, only that folder's contents are
uploaded (subfolders inside it are kept). Otherwise the whole drive is scanned.

Requires: Python 3 and rclone.exe (kept in tools/rclone/ next to this script).
"""
import json
import os
import re
import subprocess
import sys
import time

RCLONE_REMOTE = "gdrive"  # name of the remote in `rclone config`
SSD_LABEL = "Project Storage"  # external SSD: local replay copy + the tournament's VOD folder
POLL_SECONDS = 3
CODE = os.path.dirname(os.path.abspath(__file__))           # tools\\python (the scripts)
ROOT = os.path.dirname(os.path.dirname(CODE))                # project folder
HERE = ROOT  # older name, kept for compatibility
CONFIG_PATH = os.path.join(ROOT, "slippi_uploader_config.json")


# ---------- saved drive names ----------

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("drives", {})
            # Migrate older entries that were keyed by serial number to label keys.
            for key, val in list(data["drives"].items()):
                if key.startswith("serial:") and val.get("label"):
                    new_key = f"label:{val['label'].lower()}"
                    data["drives"].setdefault(new_key, val)
                    del data["drives"][key]
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"drives": {}}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ---------- drive detection ----------

def removable_drives():
    """Return a set of mount points for currently plugged-in removable drives."""
    drives = set()
    if sys.platform.startswith("win"):
        import ctypes
        import string
        DRIVE_REMOVABLE = 2
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                root = f"{letter}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(root) == DRIVE_REMOVABLE:
                    if volume_info(root)[0].lower() != SSD_LABEL.lower():  # never the SSD itself
                        drives.add(root)
    elif sys.platform == "darwin":
        for name in os.listdir("/Volumes"):
            path = os.path.join("/Volumes", name)
            if os.path.ismount(path) and not os.path.islink(path):
                drives.add(path)
    else:
        user = os.environ.get("USER", "")
        for base in (f"/media/{user}", f"/run/media/{user}", "/media", "/mnt"):
            if os.path.isdir(base):
                for name in os.listdir(base):
                    path = os.path.join(base, name)
                    if os.path.ismount(path):
                        drives.add(path)
    return drives


def volume_info(path):
    """Return (label, unique_key) for a drive. Label has no drive letter."""
    if sys.platform.startswith("win"):
        import ctypes
        name_buf = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint32(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(path), name_buf, 261,
            ctypes.byref(serial), None, None, None, 0)
        if ok:
            label = name_buf.value.strip()
            # Label is the primary identity. Serial numbers can be duplicated
            # on cloned drives, so they are only a fallback for unlabeled drives.
            if label:
                return label, f"label:{label.lower()}"
            return label, f"serial:{serial.value:08X}"
        return "", f"path:{path}"
    label = os.path.basename(path.rstrip("/"))
    return label, f"label:{label}"


def drive_identity(drive):
    return (drive, volume_info(drive)[1])


def safe_folder_name(name):
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip().rstrip(".")
    return name


def source_dir(drive):
    """Use the drive's 'Slippi' folder if it has one, else the whole drive."""
    try:
        for entry in os.listdir(drive):
            full = os.path.join(drive, entry)
            if entry.lower() == "slippi" and os.path.isdir(full):
                return full
    except OSError:
        pass
    return drive


def count_slp(path):
    n = 0
    for _, _, files in os.walk(path):
        n += sum(1 for f in files if f.lower().endswith(".slp"))
    return n


# ---------- upload ----------

def choose_folder_name(drive, cfg, used):
    """used = {folder: label} already uploaded this run. Two setups' drives can share a
    label (or be unlabeled), so a name used tonight is never offered again by default."""
    label, key = volume_info(drive)
    saved = cfg["drives"].get(key, {}).get("folder")
    default = saved or safe_folder_name(label) or "USB Drive"
    note = "saved name" if saved else "drive name"
    if default in used:
        print(f"!! '{default}' was already uploaded tonight (drive label '{used[default] or 'none'}').")
        print("!! Give this setup its own name so the two setups' replays don't mix.")
        default = None
    while True:
        prompt = (f"Folder name for this drive [{default}] ({note}) - Enter to accept, or type a new name: "
                  if default else "Folder name for this drive: ")
        answer = input(prompt).strip()
        folder = safe_folder_name(answer) if answer else default
        if folder and folder in used:
            if input(f"'{folder}' was already used tonight. Upload into the same folder anyway? [y/N]: ").strip().lower() != "y":
                continue
        if folder:
            break
        print("That name has no usable characters. Try again.")
    if cfg["drives"].get(key, {}).get("folder") != folder:
        cfg["drives"][key] = {"label": label, "folder": folder}
        save_config(cfg)
        print(f"Saved: this drive will default to '{folder}' from now on.")
    return folder


def find_rclone():
    """Prefer tools/rclone/, then next to this script, then PATH."""
    exe = "rclone.exe" if sys.platform.startswith("win") else "rclone"
    for path in (os.path.join(ROOT, "tools", "rclone", exe), os.path.join(ROOT, exe)):
        if os.path.exists(path):
            return path
    return "rclone"


def run_upload(src, dest):
    rclone = find_rclone()
    cmd = [
        rclone, "copy", src, dest,
        "--include", "*.slp",
        "--ignore-existing",
        "--transfers", "8",
        "--progress",
    ]
    return subprocess.run(cmd).returncode == 0


def find_ssd():
    """Root of the external SSD (found by volume label; its drive letter changes), else None."""
    if not sys.platform.startswith("win"):
        return None
    import string
    for letter in string.ascii_uppercase[3:]:
        root = f"{letter}:\\"
        if os.path.isdir(root) and volume_info(root)[0].lower() == SSD_LABEL.lower():
            return root
    return None


def ssd_replays_dir(tournament):
    ssd = find_ssd()
    return os.path.join(ssd, "Protocol VOD", "Melee", tournament, "replays") if ssd else None


def start_background_upload(local, dest, log):
    """Upload the SSD copy to Drive without blocking. Own process group, so Ctrl+C in this
    window doesn't kill it; output goes to a log file next to the replays."""
    cmd = [find_rclone(), "copy", local, dest, "--include", "*.slp", "--ignore-existing",
           "--transfers", "8", "--log-file", log, "--log-level", "INFO", "--stats", "30s"]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def handle_drive(drive, tournament, cfg, used, results):
    print(f"\n=== Drive detected: {drive} ===")
    src = source_dir(drive)
    total = count_slp(src)
    label = volume_info(drive)[0]
    if total == 0:
        print("No .slp files found on this drive, skipping.")
        results.append({"label": label or drive, "folder": "-", "n": 0, "ssd": "-", "status": "no replays"})
        return True
    print(f"Found {total} replays in {src} (drive label '{label or 'none'}')")
    folder = choose_folder_name(drive, cfg, used)
    dest = f"{RCLONE_REMOTE}:{tournament}/{folder}"
    replays = ssd_replays_dir(tournament)
    if replays:
        local = os.path.join(replays, folder)
        while True:
            print(f"Copying to the SSD: {local} ...")
            ok = run_upload(src, local)  # rclone copy works local -> local too (same filters)
            if ok and count_slp(local) >= total:
                break
            if input("Copy to the SSD didn't finish. Retry? [Y/n]: ").strip().lower() == "n":
                print("Falling back to a direct upload from the drive.")
                local = None
                break
        if local:
            print(f"\nCopied {total} replays to the SSD. Safe to eject this drive now.")
            log = os.path.join(replays, f"upload_{folder}.log")
            proc = start_background_upload(local, dest, log)
            print(f"Uploading to Google Drive ({tournament}/{folder}) in the background...")
            used[folder] = label
            results.append({"label": label or drive, "folder": folder, "n": total, "ssd": "ok",
                            "proc": proc, "local": local, "dest": dest, "status": "uploading"})
            return True
    while True:
        print(f"Uploading to: {tournament}/{folder} ...")
        if run_upload(src, dest):
            print(f"\nUpload complete for '{folder}'. Safe to eject this drive.")
            used[folder] = label
            results.append({"label": label or drive, "folder": folder, "n": total,
                            "ssd": "no SSD" if not replays else "failed", "status": "ok"})
            return True
        retry = input("Upload reported an error. Retry? [Y/n]: ").strip().lower()
        if retry == "n":
            print("Skipped. Do not trust this drive's upload until you re-run it.")
            results.append({"label": label or drive, "folder": folder, "n": total,
                            "ssd": "no SSD" if not replays else "failed", "status": "FAILED"})
            return False


def finish_uploads(results):
    """Wait for the background Drive uploads; offer a retry (from the SSD copy) for failures."""
    pending = [r for r in results if r.get("proc")]
    if not pending:
        return
    if any(r["proc"].poll() is None for r in pending):
        print(f"\nWaiting for {sum(r['proc'].poll() is None for r in pending)} Google Drive upload(s) to finish...")
    for r in pending:
        code = r["proc"].wait()
        r["status"] = "ok" if code == 0 else "FAILED"
        r.pop("proc")
    for r in results:
        while r.get("status") == "FAILED" and r.get("local"):
            if input(f"Drive upload for '{r['folder']}' failed. Retry from the SSD copy? [Y/n]: ").strip().lower() == "n":
                print("Skipped. The replays are safe on the SSD; re-run the uploader later.")
                break
            if run_upload(r["local"], r["dest"]):
                r["status"] = "ok"


def print_summary(tournament, results):
    if not results:
        return
    finish_uploads(results)
    print(f"\n=== Summary: {tournament} ===")
    for r in results:
        print(f"  Drive {r['status']:10} SSD {r['ssd']:7} {r['n']:4} replays  drive '{r['label']}' -> {r['folder']}")
    replays = ssd_replays_dir(tournament)
    if replays and os.path.isdir(replays):
        print(f"Local replay copy: {replays}")


def main():
    tournament = sys.argv[1] if len(sys.argv) > 1 else input("Tournament folder name (e.g. Protocol #54): ").strip()
    if not tournament:
        sys.exit("Tournament name is required.")

    cfg = load_config()
    used, results = {}, []  # folders uploaded this run; per-drive outcome for the summary
    # A drive's identity is (drive letter, volume label), so a different drive
    # that reuses the same letter is still detected as new.
    present = sorted(removable_drives())
    seen = {drive_identity(d) for d in present}
    print(f"Uploading to: {tournament}")
    replays = ssd_replays_dir(tournament)
    print(f"Local copy on the SSD: {replays}" if replays else
          f"SSD '{SSD_LABEL}' not connected: uploading straight to Google Drive (no local copy).")
    if present:
        names = ", ".join(f"{d} '{volume_info(d)[0] or 'no label'}'" for d in present)
        if input(f"Already plugged in: {names}. Upload these now? [Y/n]: ").strip().lower() != "n":
            for d in present:
                handle_drive(d, tournament, cfg, used, results)
    print("Plug in a flash drive to begin (Ctrl+C to quit).")
    try:
        while True:
            time.sleep(POLL_SECONDS)
            current = {drive_identity(d) for d in removable_drives()}
            seen &= current  # forget drives that were unplugged or swapped
            for ident in sorted(current - seen):
                drive = ident[0]
                time.sleep(2)  # let the OS finish mounting
                handle_drive(drive, tournament, cfg, used, results)
                seen.add(ident)
                again = input("\nPress Enter to wait for the next drive (or type q to finish): ").strip().lower()
                if again == "q":
                    print_summary(tournament, results)
                    print("Done.")
                    return
                print("Plug in the next flash drive...")
    except KeyboardInterrupt:
        print_summary(tournament, results)
        print("\nStopped.")


if __name__ == "__main__":
    main()
