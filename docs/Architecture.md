# Architecture

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

## The machines

| Machine | Role | Runs |
|---|---|---|
| **Stream PC** (laptop, Windows user `<stream-pc-user>`; project `%USERPROFILE%\Documents\SuperStreamBros`) | Runs the night: bracket, stream, overlay, recording | OBS (collection "Protocol Dock"), **Melee Stream Dock** (`Super Stream Bros Melee\`, port 8765), Slippi Launcher, the "Stream PC handoff" skill |
| **Ultimate TO's PC** ★ | Runs the Ultimate bracket and records it | **Ultimate Dock** (`Super Stream Bros Ultimate\`, port 8766; shipped as a zip), OBS (1-2 recordings) |
| **Render PC** (desktop, `RENDER-PC`; project `<render PC project folder>`) | Everything after the night | `slippi_uploader.py`, `vod_cutter.py` / `ssb_autopilot.py`, `ultimate_cutter.py`, `replay_render.py`, `youtube_upload.py`, `luckystats_export.py` |
| **External SSD "Project Storage"** (1 TB NVMe, USB) | Carries the recordings, dock logs, replays and finished videos between the PCs | - |
| **Setup flash drives** (one per Wii, told apart by volume label) | Slippi Nintendont writes each game's `.slp` replay | - |

Any PC with Python 3.14, ffmpeg, rclone and Slippi's playback Dolphin can be the render PC. The render needs a
GPU encoder (`h264_amf` on AMD; see Config reference for other GPUs) and a vanilla NTSC 1.02 Melee ISO.

## Data flow

```
 Tournament night                                   Day after
 ----------------                                   ---------
 Wiis + Slippi Nintendont --.slp--> flash drives ──plug in──> slippi_uploader.py ──> SSD  Protocol VOD\Melee\Protocol #N\replays\<setup>\
                                                                                  └──> Google Drive  "SSBM Replay Storage"\Protocol #N\<setup>\
 Melee Stream Dock (OBS dock) ──setups.jsonl────┐
 OBS on the Stream PC ──recording.mp4───────────┴─ Stream PC handoff ──> SSD  MeleeRecordings\Protocol-N\
 start.gg (bracket, scores, rounds, stream assignment) <──── read live by every script (STARTGG_TOKEN)

                    vod_cutter.py plan  (or ssb_autopilot.py)  ──> plan.json + review.md  [+ NEEDS_REVIEW.md]
                    vod_cutter.py render ──> sets\*.mp4, "<title> - <setup> Full VOD.mp4", upload_kit\
                    youtube_upload.py upload ──> YouTube (SoVA channel, playlist "PROTOCOL #N Melee")
                    luckystats_export.py ──> LuckyStats\Protocol #N\sets\ + zips ──(browser upload)──> luckystats.gg

 Ultimate Dock ──log.jsonl, characters.json──┐
 Ultimate OBS ──Recording 1/2.mp4────────────┴─ TO copies ──> SSD UltimateRecordings\Protocol #N\
                    ultimate_cutter.py plan/render/kit ──> Protocol VOD\Ultimate\Protocol #N\  ──> youtube_upload.py
```

## The SSD layout

```
<SSD "Project Storage">\
  MeleeRecordings\Protocol-N\            raw Melee stream recording + the dock's setups.jsonl / setups.csv / Setup times.txt   (read only)
  UltimateRecordings\Protocol #N\        raw Ultimate recordings + the TO's timestamps\protocol-N\ folder                        (read only)
  UltimateRecordings\player_characters.json   Ultimate characters per player, all weeks (written by the Ultimate Dock)
  Protocol VOD\
    Melee\Protocol #N\                   vod_config.json, plan.json, review.md, NEEDS_REVIEW.md, dock\, replays\<setup>\,
                                         work\ (caches, rendered games), sets\, Full VODs, youtube_chapters - <setup>.txt,
                                         upload_kit\ (+ uploaded_sova.json = what's on YouTube), render/upload logs
    Ultimate\Protocol #N\                the same for Ultimate (+ thumbs\, dock\ = the TO's log)
    Melee Analysis\                      optional per-player set reviews + clips (slp_analyze.py)
  Super Stream Bros\                     this package
  Render PC handoff strategy.md          how the render PC uses the handoff (2026-11-17)
  Stream laptop handoff strategy.md      how the Stream PC produces it (2026-11-17)
```

In a config `{ssd}` means "the drive labelled Project Storage", whatever its letter. Relative paths are read next
to the config.

## Scripts (`tools\python\`)

| Script | Stage | What it does |
|---|---|---|
| `slippi_uploader.py "Protocol #N"` | 1 Upload | Waits for flash drives; each is copied to the SSD tournament folder's `replays\<setup>\` (pull it as soon as it says so), then uploaded to Drive in the background (`--ignore-existing`). Drive label -> setup folder name is remembered in `slippi_uploader_config.json`. |
| `slippi_scan.py <folder>` | 2 Scan | Reads every `.slp`: Wii start time, length, stage, ports, characters, costumes, nametags, CPU/human, end method (game / LRAS quit / no contest), winner, final stocks/percent. Used by everything else; standalone it writes an inventory JSON + CSV. |
| `vod_cutter.py plan\|render\|full\|kit <vod_config.json>` | 3 Match + Melee VOD | `plan`: matches start.gg sets to replay runs (see Strategy) -> `plan.json` + `review.md`. `render`: stream sets cut from the recording with a rebuilt overlay, off-stream sets rendered from replays, per-setup Full VODs with chapters, upload kit. `--only A,B` renders single sets. |
| `ssb_autopilot.py N` ★ | Hands-off Melee | The whole Melee day-after without a person or an AI agent, stopping only when the plan needs a human (see `AI and hands-off.md`). |
| `replay_render.py <slp> <out.mp4>` | Render | Plays one replay in a private copy of Slippi's playback Dolphin with frame + audio dumping, muxes 642x528@60 + game audio. Retries a frozen Dolphin. |
| `vod_overlay.py` | Render | Builds the Melee side panel (names, pictures, stock icons, round, theme) for each game. |
| ★ `ultimate_cutter.py plan\|scan\|render\|thumbs\|kit <vod_config.json>` | Ultimate VOD | Cuts the Ultimate recordings from the Ultimate Dock's `log.jsonl`, refines each cut from VS/results screens, scoreboard overlay, VS-card thumbnails, upload kit. |
| `youtube_upload.py upload\|status\|tags\|links <folder>` | Publish | Resumable uploads in kit order, playlist + playlist description, tags/titles/descriptions sync (`tags`), Lucky Stats links in / dead Drive links out (`links`). `auth` signs in. `--account sova` = the SoVA channel. |
| `luckystats_export.py <plan.json> <replays> <out>` | 4 Export | One folder per set: `01.slp`, `02.slp`... + `context.json` (see `Lucky Stats.md`). |
| `slp_repair.py` | Rescue | Writes a repaired copy of a replay with flipped bits (failing flash drive); the original is untouched. |
| `slp_analyze.py` | Extra | Frame-by-frame coaching stats for one player's sets (openings, conversions, pace...). |
| `rclone_own_client.py` | Setup | Moves the `gdrive` rclone remote onto your own Google OAuth client (one browser sign-in). |

`tools\corsair_mouse_channels_OFF.bat` / `_ON.bat`: Windows only, for PCs with that Corsair mouse; see Troubleshooting
("every Dolphin start takes 40 s").

## External services

| Service | Used for | Credential |
|---|---|---|
| start.gg GraphQL API | sets, scores, rounds, entrants, stream assignment; the docks also report scores | Personal access token in the `STARTGG_TOKEN` user environment variable (start.gg > profile > Developer settings) |
| Google Drive (via rclone) | replay backup + "Replays:" links in video descriptions | rclone remote `gdrive`, `root_folder_id` = the "SSBM Replay Storage" folder; token in `%APPDATA%\rclone\rclone.conf` |
| YouTube Data API v3 | uploads, playlists, descriptions | OAuth desktop client `%APPDATA%\ProtocolVOD\client_secret*.json`, tokens `youtube_token*.json` |
| Lucky Stats (luckystats.gg) | public set pages with replays + stats | browser upload of zips; no API used |
