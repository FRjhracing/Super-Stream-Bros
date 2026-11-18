# Super Stream Bros

**From a Smash bracket night to a finished VOD library with stats, in one tool set.** Run the start.gg bracket
and the stream overlay from browser/OBS docks, collect the Slippi replays from every setup, cut the stream and
the off-stream replays into one YouTube video per set (plus a Full VOD per setup), and publish every set with
stats on Lucky Stats. Plain Python (standard library) and local web pages; an AI agent is optional.

Built for and used every week at **PROTOCOL\***, a weekly Super Smash Bros. Melee + Ultimate tournament
([start.gg/ProtocolSOVA](https://www.start.gg/ProtocolSOVA)).

## Proven at three tournaments

The full Melee pipeline (dock setup log → replays → matched sets → rendered videos → YouTube → Lucky Stats) ran
end to end at three consecutive PROTOCOL events:

| Event | Date | Bracket | Lucky Stats (every set, with stats) | YouTube |
|---|---|---|---|---|
| PROTOCOL #58 | 2026-11-02 | [start.gg](https://www.start.gg/tournament/protocol-58) | [event 310766](https://luckystats.gg/event/310766) | 26 videos on [@SOVA_Protocol](https://www.youtube.com/@SOVA_Protocol) |
| PROTOCOL #59 | 2026-11-09 | [start.gg](https://www.start.gg/tournament/protocol-59) | [event 316304](https://luckystats.gg/event/316304) | 28 videos on [@SOVA_Protocol](https://www.youtube.com/@SOVA_Protocol) |
| PROTOCOL #60 | 2026-11-16 | [start.gg](https://www.start.gg/tournament/protocol-60) | [event 323683](https://luckystats.gg/event/323683) | 21 videos on [@SOVA_Protocol](https://www.youtube.com/@SOVA_Protocol) |

What those nights threw at it, and it handled: sets on stream plus three off-stream setups each night, a Wii
clock an hour off (daylight time) and one a year off, a stream recording started mid-game, a quit-out on the last
stock, grand final + reset played back to back, a dock setup renamed mid-set and 24 minutes of lost stream audio
rebuilt from the replays (`docs\Strategy.md` has the list week by week).

## How mature each part is

| Part | Status |
|---|---|
| Melee dock (bracket, overlay, setup log), Slippi replay upload, Melee VOD cutter (`vod_cutter.py` plan/render), YouTube upload, Lucky Stats export | **Used at every event above** |
| Seasonal themes (round names + overlay) | Used live (Halloween, PROTOCOL #57); `make_theme_art.py` for your own panel is new |
| OBS scene generator (`tools\obs\`) | New; tested by importing into OBS 33 |
| ★ Hands-off autopilot (`ssb_autopilot.py`) | **Beta** |
| ★ Ultimate workflow (Ultimate dock → `ultimate_cutter.py` → videos) | **Beta** |
| ★ LAN / multi-TO mode for bigger events (`guides\06`) | **Beta**, not yet used at an event |

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug, an unclear step or a setup it
> doesn't handle? **[Open an issue](https://github.com/FRjhracing/Super-Stream-Bros/issues)** (FRjhracing).

## Get started

Clone or download this repository, then open **`START HERE.html`** in your browser (the guides are interactive
HTML pages with checklists and screenshots; GitHub shows only their source).

1. `guides\01 Install and setup.html`: Python, ffmpeg, rclone, Slippi, OBS, start.gg token, Google sign-ins.
2. `guides\05 Stream PC dock and OBS.html`: the Melee dock, an OBS scene built from your layout, themes, Wiis.
3. `guides\02 Weekly workflow.html`: tournament night and the day after.
4. Your own look: `guides\04 Overlay layout map.html` and `tools\render\overlays\melee_themes\PROVIDE YOUR OWN.md`.

\* **PROTOCOL** is the weekly series these tools were built for. Its names, links, stream name, setup names and
layout appear throughout the docs and examples as real-world samples ("PROTOCOL's layout", "Protocol #60",
`ProtocolSOVA`, `frjhracing`): swap in your own series, start.gg short link, stream and setups.

No third-party software, PROTOCOL's own overlay art or its font are included: `guides\01 Install and setup.html`
links each download, and generic sample art stands in until you add your own. Not affiliated with Nintendo,
start.gg, Slippi, Lucky Stats or YouTube.

## License

[GPL-3.0](LICENSE). Lucky Stats set generation follows the format of
[0xburn/auto-vlerk-game-data-mapper](https://github.com/0xburn/auto-vlerk-game-data-mapper) (credit in `docs\Lucky Stats.md`).

## What's in here

| Path | What |
|---|---|
| `START HERE.html` | Overview, diagram, links to everything |
| `guides\01 Install and setup.html` | Interactive install checklist for both PCs (downloads, accounts, sign-ins) |
| `guides\02 Weekly workflow.html` | Interactive checklist for tournament night and the day after (manual and autopilot paths) |
| `guides\03 YouTube API audit form.html` | Answers for Google's YouTube API audit form (only needed to lift the Private-upload lock) |
| `guides\06 LAN and multi-TO events.html` | Larger events: one hub PC runs the docks for TO tablets (staff PIN) and bracket screens (view PIN) on an event LAN, a dock instance per stream, overlay files shared to the stream PCs, settings for big brackets |
| `guides\05 Stream PC dock and OBS.html` | The Stream PC with screenshots: Melee dock setup and pages, OBS scene from your layout, recording settings, themes, Wiis and flash drives, the handoff by hand |
| `docs\Architecture.md` | The two PCs, the SSD, every script, how data flows |
| `docs\Strategy.md` | How the data is combined (replays, dock logs, start.gg, recordings) and the lessons learned week by week |
| `docs\AI and hands-off.md` | What works with and without an AI agent; the hands-off autopilot and its limits |
| `docs\Lucky Stats.md` | Lucky Stats set generation (context.json format, credit to the original GitHub project) |
| `docs\Config reference.md` | Every `vod_config.json` key (Melee and Ultimate) |
| `docs\Troubleshooting.md` | Known failures and their fixes |
| `docs\reference\` | Full project notes, the handoff strategy files and the checklist the package was finished with, as they stood on 2026-11-17/18 |
| `tools\python\` | All the scripts (stdlib Python 3.14, no pip packages) |
| `tools\render\overlays\` | Overlay code, layouts and **generic sample art** (blank panel, plain pictures, "YOUR LOGO" emblem). Renders work out of the box with a standard Windows font; replace the samples with your own art (`PROVIDE YOUR OWN.md` in each folder, and `guides\04 Overlay layout map.html` for what goes where). `tools\render\make_sample_assets.py` redraws the samples to match a custom `layout.json` |
| `guides\04 Overlay layout map.html` | Visual map: which asset or data fills each spot of the rendered Melee panel and Ultimate scoreboard, and how to adapt to a different stream layout |
| `tools\render\overlays\melee_themes\` | **The one stream look** for the dock, OBS and the renderer: `layout.json` (positions), `Default\` + seasonal theme folders (`theme.json` round names, `overlay.png`), `make_theme_art.py` (draws a seasonal version of your own panel; examples `Halloween\`, `Winter\`) |
| `tools\ffmpeg\`, `tools\rclone\`, `tools\render\slippi_playback\` | Empty: install the third-party tools here (see the setup guide) |
| `tools\render\docks\melee\` | Melee dock: start.gg bracket + stream overlay files + themes + setup log (port 8765). Stock icons and font not included (`assets\*\PROVIDE YOUR OWN.md`) |
| `tools\render\docks\ultimate\` | Ultimate dock for the Ultimate TO: bracket + recording timestamps + characters (port 8766); shipped to them as a zip (`README.md`, `SETUP.txt`) |
| `tools\obs\make_obs_scenes.py` | Builds an importable OBS scene collection from `layout.json` (paths to the dock's `output\`) |
| `examples\` | Example configs |

## The weekly loop in one paragraph

On the night, the **Stream PC** runs the Melee **Stream Dock** next to OBS (bracket control + overlay + a setup log),
streams and records the main setup to the external SSD **"Project Storage"**; the Ultimate TO runs the
**Ultimate Dock** and records Ultimate. Every Wii writes Slippi replays to a flash drive. The day after, the
Stream PC hands off the recording + dock log on the SSD, and the **Render PC** uploads the flash drives
(`slippi_uploader.py`), plans and renders the Melee videos (`vod_cutter.py`, or `ssb_autopilot.py` for the
hands-off path), cuts Ultimate from its dock log (`ultimate_cutter.py`), uploads to YouTube
(`youtube_upload.py`) and exports the sets for Lucky Stats (`luckystats_export.py`).

## Ground rules

- Replays (`.slp`) and raw recordings are **read-only**. Scripts copy, never modify them.
- Uploads never delete: `rclone` runs with `--ignore-existing`; never `rclone sync`/`delete`/`purge` on `gdrive:`.
- Secrets never go in files or notes: the start.gg token lives in the `STARTGG_TOKEN` environment variable, the
  Slippi `playKey` stays in Slippi's own `user.json`, Google tokens stay in `%APPDATA%`.
- The SSD is found by its **volume label** ("Project Storage"), never by drive letter. Flash drives are told
  apart by **volume label** too (their serial numbers repeat).
- Superseded files go to an `_archive\` folder instead of being deleted.
