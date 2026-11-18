# Config reference

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

One `vod_config.json` per tournament, in `<SSD>\Protocol VOD\Melee|Ultimate\Protocol #N\`. Keys starting with
`_` are notes and are ignored, so write the why next to every hand fix (`"_note": "..."`). Save as UTF-8
**without** a BOM (PowerShell's `Set-Content` adds one and breaks `json.load`; use an editor, Python, or let the
autopilot write it). `{ssd}` = the drive labelled "Project Storage". Relative paths = next to the config.

Examples: `examples\vod_config.melee.example.json`, `examples\vod_config.ultimate.example.json`.

## Melee (`vod_cutter.py`, `ssb_autopilot.py`)

| Key | Default | Meaning |
|---|---|---|
| `tournament` | (required) | start.gg tournament slug, e.g. `protocol-60` |
| `title` | the slug | used in video titles/file names, e.g. `PROTOCOL #60` |
| `recording` | (required) | the OBS stream recording; its file name `YYYY-MM-DD HH-MM-SS` is the time base |
| `replays` | `replays` | folder with one subfolder per setup (names = the setups) |
| `stream_setup` | (required) | the setup folder that is on stream, e.g. `Main Setup` |
| `stream_name` | - | our start.gg stream name; sets assigned to it are tried on the stream setup first |
| `dock_log` | - | the Melee dock's `setups.jsonl` (e.g. `dock/setups.jsonl`) |
| `dock_setups` | - | dock setup name -> replay folder, when the names differ beyond case/"setup"/plural (`{"Setup 3": "BJH"}`) |
| `clock_offset_s` | `{}` = 0 | per setup: seconds the Wii clock is **ahead** of the laptop, or `{"wii": "2025-11-16 20:00:00", "laptop": "2026-11-16 20:00:00"}` (same moment on both clocks). Stream setup: calibrated so a game's video time = GO |
| `sets` | `{}` | per set letter (start.gg identifier), see below |
| `drive_folder` | `title` | Google Drive folder for the "Replays:" links |
| `luckystats` | - | `{"_event": "<event URL>", "<set letter>": "<set id or URL>"}` for the description links |
| `season` | - | theme folder name (e.g. `Halloween`): that theme's overlay + round names on rebuilt overlays |
| `overlay_stream` | `true` | rebuild the overlay panel on stream sets too |
| `include_offstream` | `true` | render off-stream sets from replays |
| `pad_before_s` / `pad_after_s` | 10 / 10 | seconds kept before the first game / after the last |
| `gain_db` | 10 | stream audio boost (a limiter keeps it under 0 dBFS) |
| `account` | `"sova"` | YouTube account for the kit (`null` = the main channel) |
| `title_full`, `title_set`, `title_set_short` | see `vod_cutter.py` | title templates; fields `{tournament} {setup} {round} {a} {b} {a_char} {b_char}` |
| `replay_repairs` | - | `{"<setup>/<file>.slp": "<repaired copy>"}` from `slp_repair.py` |
| `media_dir` | next to the config (on the SSD) | where the videos go, if not next to the config |

Per-set overrides, `"sets": {"<letter>": {...}}`:

| Key | Meaning |
|---|---|
| `games` | exact replay file names for the set (no checks); use for sets the matcher can't find |
| `score` | `[a, b]` when start.gg's reported score is wrong |
| `setup` | only look on this setup |
| `skip` | leave the set out (`"reason"` for the review) |
| `replay_games` | stream sets: `"all"` or `[n, ...]` = rebuild those games' picture and sound from the replays (stream audio missing); the webcam stays live |

Written by the autopilot (and fine to edit): `clock_offset_s._autopilot` (confidence per setup),
`dock_setups._autopilot`, `sets.<X>.replay_games` + `_autopilot` for audio dropouts.

## Ultimate (`ultimate_cutter.py`) ★

| Key | Meaning |
|---|---|
| `tournament`, `title` | as Melee |
| `game` | `"Ultimate"` (titles/playlist "PROTOCOL #N Ultimate") |
| `account` | `"sova"` |
| `recordings` | `{"1": "{ssd}/UltimateRecordings/Protocol #N/<file>.mp4", "2": ...}` (recording number = the dock's) |
| `recording_names` | `{"1": "Main 1"}` (names in Full VOD titles) |
| `dock` | folder with the TO's `log.jsonl` + `characters.json` (e.g. `dock`) |
| `player_characters` | the Ultimate Dock's all-weeks `player_characters.json` (thumbnail fallback) |
| `pad_before_s` / `pad_after_s` | 15 / 15 |
| `gain_db` | fixed gain; default = raise each set to a mean of -20 dB (max +30) |
| `overlay` | `true` = scoreboard overlay |
| `refresh_startgg` | `true` = ignore the cached start.gg data |
| `tags`, `title_full`, `title_set_short`, `media_dir` | as Melee |
| `sets.<letter>` | `rec` + `start` + `end` (`"h:mm:ss"`) to cut a set by hand; `chars` `{"<player>": ["<char>", ...]}`; `skip`; `note` |

## Per-PC settings: `machine_settings.json` (project root)

Keyed by the Windows computer name (`%COMPUTERNAME%`):

```json
{ "RENDER-PC-NAME": { "iso": "D:\\Games\\Melee\\SSBM NTSC 1.02.iso", "render_speed": 4.0 } }
```

- `iso`: vanilla NTSC 1.02 Melee ISO (MD5 `0e63d4223b01d9aba596259dc155a174`).
- `render_speed`: emulation speed ceiling for replay renders. Must be frame-exact: check the in-game timer of a
  rendered game. A fast desktop renders at ~2x real time (Dolphin's AVI writer is the limit); a laptop iGPU
  needed 0.85.

## Flash drive labels: `slippi_uploader_config.json` (project root)

Remembered `volume label -> setup folder name`, e.g. `SETUPONE -> Main Setup`. The uploader asks the first time
it sees a label. Two drives with the same label on one night are refused (rename one in Windows).
