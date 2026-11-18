# Troubleshooting

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

## Sign-ins and uploads

| Symptom | Cause | Fix |
|---|---|---|
| `invalid_grant: Token has been expired or revoked` (rclone or YouTube) | The Google OAuth app is in **Testing** mode (sign-ins expire after 7 days), or the token was revoked | Publish the app (Google Cloud > OAuth consent screen > Audience > Publish app). Then sign in again: `tools\rclone\rclone.exe config reconnect gdrive:` / `python tools\python\youtube_upload.py auth [--account sova]` (interactive: type it yourself) |
| rclone upload fails on every file with **403 `insufficientParentPermissions`** | rclone was signed in to a **different Google account** that can see the folder but not write to it | `rclone about gdrive:` shows ~0 B used = wrong account. `rclone config reconnect gdrive:` and pick the account that owns "SSBM Replay Storage". Then re-run the upload (`--ignore-existing` skips what's there) and check with `rclone check <local> "gdrive:Protocol #N/<setup>" --one-way` |
| YouTube uploads arrive **Private** | Unaudited API projects can only upload Private | Publish in YouTube Studio (select all > Visibility), or pass Google's audit (`guides\03`) |
| "quota exceeded" | Daily YouTube API limit | Run the same upload command after midnight Pacific; it resumes. A normal week (~25 videos) fits in one day |
| Upload went to the wrong channel | Old kits have no `account` | `--account sova`; check with `youtube_upload.py status <folder>` |

## Replays and matching

| Symptom | Cause | Fix |
|---|---|---|
| A set shows the wrong players' characters (e.g. a Falcon main "playing" Dr. Mario) | **Wrong clock offset** for that setup made other games fit | Re-check the setup's offset against the dock windows (the autopilot does this); never explain it away as counterpicks without checking |
| A set is missing: "no run of games fits the score" | wrong offset, a missing replay (stick inserted late), or a wrong start.gg score | fix the offset; `"score": [a, b]` override; or list the games with `"games"` |
| "candidate run(s) were all taken by other sets" | two sets competing for the same games (e.g. back-to-back sets between the same players are now split automatically) | `"games"` override for both sets |
| A handwarmer counted as game 1, or a real game 1 trimmed as a handwarmer | handwarmers are inferred (identical characters right before the set) | confirm with the players; `"games"` override |
| A quit-out game is missing | only last-stock quit-outs in the middle of a set count | `"games"` override if the players agree it counted |
| Dolphin refuses a replay / render stops "closed early" / scan stops mid-game | corrupted replay (failing flash drive: bit flips in a 4 KB block) | `slp_repair.py` writes a fixed copy; point `"replay_repairs"` at it; retire the flash drive |
| Two flash drives have the same label | Windows default labels ("USB DRIVE") | rename the drive in Explorer; the uploader refuses a label twice in one night |

## Rendering

| Symptom | Cause | Fix |
|---|---|---|
| A replay render freezes (frame counter stops) | Dolphin window clicked / lost focus, or a random hang | retried automatically 3 times; don't touch the Dolphin windows during a render. Re-running `render` continues (finished games are cached in `work\set_X\`) |
| **Every Dolphin start takes ~40 s** | DirectInput enumeration waits 10 s on each of 4 HID interfaces of some Corsair mice (VID 1B1C PID 1B3E), even with iCUE closed | `tools\corsair_mouse_channels_OFF.bat` (admin) disables just those interfaces (pointer keeps working; iCUE loses the mouse); `_ON.bat` restores. Other HID devices can do the same: unplug-test |
| Objects missing in the first frames of rendered games | async shader compilation | playback Dolphin: `FullAsyncShaderCompilation = False`, `CompileShaderOnStartup = True` (setup guide) |
| Game clock runs ahead of the video in renders | emulation speed too high for that PC: frames dropped | lower `render_speed` in `machine_settings.json` until the in-game timer is frame-exact |
| No sound in a stream set | OBS lost the audio | the autopilot ★ detects digital silence and sets `replay_games`; by hand: `"sets": {"E": {"replay_games": "all"}}` |
| `Stream font ... not found` | the font file isn't installed / provided | put your font file where `PROVIDE YOUR OWN.md` says |
| `h264_amf` errors | no AMD GPU | change `ENC` in `vod_cutter.py` to `h264_nvenc` (NVIDIA), `h264_qsv` (Intel) or `libx264` (CPU, slow) |
| Cutting is slow, SSD drops off mid-write | SSD on a hub / USB 2.0 port | plug the SSD into a rear USB 3.1+ port with a 10 Gbps+ cable (reads ~280 MB/s) |

## Stream PC / docks

| Symptom | Cause | Fix |
|---|---|---|
| Docks take 20-60 s to load | start.gg's IPv6 address times out on some networks | the docks and scripts prefer IPv4; keep that `getaddrinfo` wrapper in any new code |
| start.gg 429 / "complexity too high" stalls the dock poll | rate limit / big queries | fixed in the 2026-11-11 dock build (25 sets per page, under 55 reads/min) |
| Headless screenshot tests of a dock never finish | the page's long-poll | add `?nowatch` to the URL |
| Ultimate night has no `log.jsonl` | the TO copied only the `.txt` exports | copy the whole `timestamps\protocol-N\` folder; without `log.jsonl` the Ultimate cut is empty |

## Files

- `json.decoder.JSONDecodeError: Unexpected UTF-8 BOM`: a config saved by PowerShell `Set-Content`/`Out-File`.
  Re-save as UTF-8 without BOM.
- Never edit `.slp` files or the raw recordings; every tool works on copies.
