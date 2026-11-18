# Docks

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

Two small local web apps (Python standard library, no installs beyond Python) that run the start.gg bracket
from a browser tab or an OBS dock and keep a time log of every set, which the VOD tools on the render PC read.

| Folder | Port | Runs on | What it does |
|---|---|---|---|
| `melee\` | 8765 | the Stream PC (OBS) | Bracket controls + the **stream overlay** (writes the files OBS shows) + seasonal themes + the setup log `setups.jsonl` |
| `ultimate\` ★ | 8766 | the Ultimate TO's PC | Bracket controls + **recording timestamps** for two recordings + setup log + characters per set. No overlay |

Both can run on one PC at the same time (different ports). Both are this-PC-only by default; for an event LAN
with several TOs, tablets and bracket screens (a central hub PC, PINs, more than one stream, big brackets) see
**`guides\06 LAN and multi-TO events.html`**. Visual walkthrough:
**`guides\05 Stream PC dock and OBS.html`**. Melee details: `melee\README.md`; Ultimate: `ultimate\SETUP.txt`
(written for the person running it) and `ultimate\README.md` (shipping it as a zip).

## First start (both)

1. Python 3.14 from python.org (`guides\01 Install and setup.html`); no pip packages.
2. `set_token.bat`: paste a start.gg personal access token from an admin of the tournament. It is stored as the
   Windows user variable `STARTGG_TOKEN`, never in a file.
3. `start_dock.bat` (leave the window open), then `open_docks.bat` (opens Home, Full Bracket, Active Bracket
   in the browser) or add the pages to OBS as Custom Browser Docks.
4. The first start writes `dock_config.json` next to `dock_server.py`. Set `"shortLink"` to your series'
   start.gg short link (the `start.gg/<name>` link that always opens your newest tournament) and restart, or
   type a tournament slug in ⚙ > Load slug.

## Files the docks write (not shipped, don't commit)

| File / folder | What |
|---|---|
| `dock_config.json` | your settings (series link, setups, stream, theme, colours) |
| `dock_state.json`, `setup_state.json`, `player_prefs.json` | what is on stream / on each setup now; each player's last character |
| `output\` | Melee: the overlay files OBS reads |
| `timestamps\<tournament-slug>\` | the logs handed to the render PC (`RENDER_PC_HANDOFF` in `docs\reference\`) |
| `ultimate\player_characters.json` | Ultimate: every player's characters (personal data of your players: keep it local) |

## Art the Melee dock uses (not shipped)

`melee\assets\default.png` (a plain sample is included: picture for players without one),
`melee\assets\stock_icons\` (see its `PROVIDE YOUR OWN.md` for the 123 file names) and
`melee\assets\fonts\` (optional, your stream font for measuring names). The stream overlay and its themes live in
`tools\render\overlays\melee_themes\`, shared with the VOD renderer.
