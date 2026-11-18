#!/usr/bin/env python3
"""
Point the rclone remote "gdrive" at our own Google OAuth client (rclone's shared client_id is
being retired during 2026), then sign in again.

Uses the same Desktop-app client JSON as youtube_upload.py: %APPDATA%\\ProtocolVOD\\client_secret.json
(the project needs "Google Drive API" enabled). Prints neither the secret nor the token.

Run from the project folder:   python tools\\python\\rclone_own_client.py
A browser opens for the Google sign-in (same account that owns "SSBM Replay Storage").
root_folder_id, scope and the rest of the remote stay as they are.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RCLONE = os.path.join(os.path.dirname(HERE), "rclone", "rclone.exe")  # HERE = tools\\python
CLIENT_FILE = os.path.join(os.environ.get("APPDATA", ""), "ProtocolVOD", "client_secret.json")


def main():
    if not os.path.isfile(CLIENT_FILE):
        raise SystemExit(f"Missing {CLIENT_FILE} (see README 'YouTube upload').")
    with open(CLIENT_FILE, encoding="utf-8") as f:
        d = json.load(f)
    c = d.get("installed") or d
    print("Setting gdrive's client_id/client_secret ...")
    subprocess.run([RCLONE, "config", "update", "gdrive", "client_id", c["client_id"],
                    "client_secret", c["client_secret"], "--non-interactive"],
                   check=True, stdout=subprocess.DEVNULL)
    print("Signing in again (browser opens) ...")
    subprocess.run([RCLONE, "config", "reconnect", "gdrive:", "--auto-confirm"], check=True)
    print("Checking ...")
    r = subprocess.run([RCLONE, "lsd", "gdrive:"], capture_output=True, text=True)
    print(r.stdout or r.stderr[-500:])
    if "client_id" in (r.stderr or ""):
        print("Note: rclone still mentions the shared client_id; check the remote's settings.")
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
