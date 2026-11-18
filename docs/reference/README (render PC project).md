# Slippi Tournament Tools (Protocol Melee)

Weekly tooling for the Protocol Melee series: run the bracket and stream overlay from OBS, upload replays from the setup flash drives to Google Drive, and cut the stream recording (plus off-stream sets rendered from replays) into a full VOD and per-set videos for YouTube.

## Layout

Desktop copy (render PC). Render sources live in `tools\render\` since 2026-11-11; the stream laptop's
copy still has `StreamDock\` and `Seasonal\` at the top (OBS reads them there).

```
Melee_Tournaments\
  README.md                    <- this file
  CLAUDE.md                    <- guide for Claude Code sessions
  PROJECT_NOTES.md             <- Slippi tools + Stream Dock: stages, decisions, open questions
  VODCUTTER_PROJECT_NOTES.md   <- VOD Cutter: requirements, tools, results, open questions
  RENDER_PC_HANDOFF.md         <- dock log formats handed to the render PC
  ExternalLinks.txt            <- paths to related programs on this PC
  slippi_uploader_config.json  <- remembered drive label -> folder names
  machine_settings.json        <- per-PC render settings (ISO, render_speed), keyed by computer name
  LuckyStats\<tournament>\     <- Lucky Stats zips for the week (deleted once Lucky Stats is verified)
  tools\
    rclone\                    <- rclone.exe + docs
    ffmpeg\bin\                <- ffmpeg / ffprobe / ffplay
    python\                    <- all the Python scripts (run them from the project folder):
      slippi_uploader.py       <- Stage 1: flash drive -> Google Drive
      slippi_scan.py           <- Stage 2: replay inventory (JSON + CSV)
      vod_cutter.py            <- Melee VOD: plan / render / full / kit (matching = Stage 3)
      ultimate_cutter.py       <- Ultimate VOD: plan / scan / render / thumbs / kit (from the TO's dock log)
      replay_render.py         <- render one .slp to .mp4 (playback Dolphin frame dump)
      vod_overlay.py           <- rebuilds the Melee stream overlay for rendered sets
      youtube_upload.py        <- uploads an upload kit (all Protocol videos go to the SoVA channel)
      luckystats_export.py     <- plan.json + replays -> Lucky Stats set folders (context.json)
      slp_analyze.py           <- frame-by-frame set analysis (coaching stats, clip moments)
      slp_repair.py            <- repairs damaged .slp copies (originals untouched)
      rclone_own_client.py     <- one-time: move the gdrive remote to our own Google client (opens a sign-in)
    corsair_mouse_channels_OFF.bat / _ON.bat  <- desktop: switch off/on the Corsair mouse channels
                                  that make every Dolphin start wait ~40 s (asks for admin)
    render\                    <- everything the renders draw with
      slippi_playback\         <- private copy of Slippi's playback Dolphin (frame/audio dumping on)
      overlays\
        melee_themes\          <- Melee stream looks, one folder per theme (Default, Halloween, ...):
                                  theme.json + overlay.png (+ the stream font in Default\)
        ultimate\              <- Ultimate scoreboard: layout.json, frame.png, make_frame.py,
                                  ultimate_overlay.py, fonts\, char_art\ (start.gg character renders)
      docks\
        stream_dock\           <- desktop copy of the Melee Stream Dock (stock icons, default picture)
        ultimate_dock\         <- the Ultimate TO's dock (shipped as a zip; self-contained)
      art\
        channel\               <- SoVA YouTube channel picture + banner (make_sova_*.py)
        tournament_page\       <- start.gg page art per tournament
  _archive\                    <- superseded files
```

**Tournament folders live on the external SSD "Project Storage"** (since 2026-11-11), one per event:

```
<SSD>\
  MeleeRecordings\Protocol-N\       <- raw Melee stream recording (OBS records here; read only)
  UltimateRecordings\Protocol #N\   <- raw Ultimate recordings + the TO's dock files (read only)
  Protocol VOD\
    Melee\Protocol #N\              <- replays\<setup>\ (copied there by the uploader), vod_config.json, plan.json, review.md, render logs,
                                       dock\ (Melee dock log), upload_kit\ (+ uploaded_*.json records),
                                       work\ (caches, rendered games), sets\, Full VODs, YouTube chapters
    Ultimate\Protocol #N\           <- the same for Ultimate (+ thumbs\; dock\ = the TO's log)
    Melee Analysis\                 <- set reviews + clips
```

In a config, `{ssd}` means the SSD whatever its drive letter (`"recording": "{ssd}/MeleeRecordings/..."`),
and relative paths are read next to the config (`"dock_log": "dock/setups.jsonl"`).

## Weekly use (PowerShell, from this folder)

1. Before the tournament: double-click `StreamDock\start_dock.bat`, open OBS (collection "Protocol Dock"). In the dock's ⚙: **Use latest (ProtocolSOVA)**, pick our stream, and pick the **Seasonal theme** (Default unless it's a themed week).

### Adding a seasonal theme (Christmas, #75 special, anniversary...)
Copy `Seasonal\Halloween\` (desktop: `tools\render\overlays\melee_themes\Halloween\`) to a new folder (e.g. `Christmas\`), edit `theme.json` (`name`, `rounds`: start.gg name -> stream name, `{n}` = round number, `"Losers Top 8"` = losers round with 4 left; `finalsLabel` + `finalsFrom` 4 or 8 = label on the last rounds in the bracket overview), and put the finished overlay (same size as `Default\overlay.png`, 3638x6482) in it as `overlay.png`. Leave out `rounds` or `overlay.png` to keep the normal ones. It shows up in the dock's ⚙ list after a refresh.
2. After the tournament, with the SSD plugged in: `python tools\python\slippi_uploader.py "Protocol #N"`, then plug in the flash drives one at a time. Each drive is copied to `<SSD>\Protocol VOD\Melee\Protocol #N\replays\<setup>\` (pull it as soon as it says so) and uploaded to Google Drive in the background; the summary at the end shows both copies.
3. The recording is on the SSD (`<SSD>\MeleeRecordings\`); put it and the Melee dock's `timestamps\protocol-N\` files in `MeleeRecordings\Protocol-N\`.
4. The replays are already on the SSD (`replays\` in the tournament folder). Only if they were uploaded elsewhere: `.\tools\rclone\rclone copy "gdrive:Protocol #N" "I:\Protocol VOD\Melee\Protocol #N\replays"`.
5. Make `<SSD>\Protocol VOD\Melee\Protocol #N\` with a `dock\` folder (copy the dock's `setups.jsonl` etc. into it), copy last week's `vod_config.json` in, update title / tournament / recording (`{ssd}/MeleeRecordings/...`) / replays / clock offsets (Main Setup's Wii clock is reset by hand every week: calibrate it from the in-game timer; themed week: add `"season": "Halloween"` etc.), then:
   - `python tools\python\vod_cutter.py plan "I:\Protocol VOD\Melee\Protocol #N\vod_config.json"` (use the SSD's letter) and read `review.md`
   - `python tools\python\vod_cutter.py render "I:\Protocol VOD\Melee\Protocol #N\vod_config.json"` (videos land in the same folder)
   - `python tools\python\youtube_upload.py upload "I:\Protocol VOD\Melee\Protocol #N"` (SoVA channel)
   - Ultimate: the same with `ultimate_cutter.py` in `I:\Protocol VOD\Ultimate\Protocol #N\`
6. Lucky Stats: `python tools\python\luckystats_export.py "I:\Protocol VOD\Melee\Protocol #N\plan.json" "I:\Protocol VOD\Melee\Protocol #N\replays" "LuckyStats\Protocol #N\sets"`, zip each set, upload the zips. Put the event link in vod_config (`"luckystats": {"_event": "<url>"}`), then `python tools\python\vod_cutter.py kit ...` and `python tools\python\youtube_upload.py tags "I:\Protocol VOD\Melee\Protocol #N"`.
7. Once Lucky Stats is verified: delete the tournament folder's `replays\` on the SSD and `LuckyStats\Protocol #N\`. The Drive folder `Protocol #N` is the fail-safe; delete it by hand when it's 2 weeks old.

## Requirements

- Python 3 (3.14 installed). No pip packages needed.
- rclone remote `gdrive` (configured, root = `SSBM Replay Storage`). Check with `.\tools\rclone\rclone lsd gdrive:`.
- ffmpeg is not on PATH; scripts use `tools\ffmpeg\bin\ffmpeg.exe`.
- start.gg token in the `STARTGG_TOKEN` user environment variable.

## Secrets

Never put your Slippi `playKey` or start.gg token in this folder. The start.gg token goes in the `STARTGG_TOKEN` environment variable.
