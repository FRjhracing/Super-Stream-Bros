# Super Stream Bros Melee dock

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

Runs the Melee bracket on start.gg and the stream overlay from three pages, and logs which set was played on
which setup and when (the render PC cuts the VODs from that log). Visual guide with screenshots:
`guides\05 Stream PC dock and OBS.html`.

```
start_dock.bat        starts the server on http://127.0.0.1:8765/ (keep its window open)
open_docks.bat        starts it if needed and opens the three pages in the default browser
set_token.bat         saves your start.gg token as the STARTGG_TOKEN user variable
dock_server.py        the server (Python standard library only)
lan.py                optional LAN access with PINs (off by default; guides\06)
static\               the pages: Home (/), Full Bracket (/bracket), Active Bracket (/active)
assets\               default.png (sample included), stock_icons\ and fonts\ (provide your own)
```

## Pages

| Page | URL | For |
|---|---|---|
| Super Stream Bros - Home | `http://127.0.0.1:8765/` | On stream panel (names, characters, round, Update overlay), open sets with Put on stream / Put on setup / Call / Start / Report, recent results with Reset, ⚙ settings |
| SSB:Full Bracket | `/bracket` | The whole bracket (tabs: Full / Winners / Losers / Completed sets); tap a set for its buttons. Good on a touch screen |
| SSB:Active Bracket | `/active` | Only the rounds being played, with a suggested call order (closest seeds first) |

Use them as browser tabs (`open_docks.bat`) or inside OBS: **Docks > Custom Browser Docks**, one line per page
(name + URL), Apply, then drag each dock where you want it.

## Settings

In ⚙ on Home: tournament slug / **Use latest (series link)**, our stream on start.gg ("Put on stream" assigns
sets to it), number and names of setups (the first is always "Main Setup") and which one is on stream, the
**seasonal theme**, dock colours. Saved in `dock_config.json`, kept week to week.

Only in `dock_config.json` (stop the dock, edit, start it again):

| Key | Default | Meaning |
|---|---|---|
| `shortLink` | `""` | your series' start.gg short link, e.g. `"https://www.start.gg/YourSeries"`: **Use latest** follows it to the newest tournament |
| `themesFolder` | `""` | where the theme folders are. Empty = `..\..\overlays\melee_themes` (this package: shared with the VOD renderer), else `..\Seasonal`. Absolute, or relative to this folder |
| `pollSeconds` | `20` | how often the pages refresh the bracket |
| `port` | `8765` | the dock's port (the env var `SSB_MELEE_DOCK_PORT` wins if set; `open_docks.bat` assumes 8765) |
| `tokenVar` | `"STARTGG_TOKEN"` | which user variable holds the start.gg token (a second dock on the same PC gets its own: `set_token.bat STARTGG_TOKEN_STREAM2`) |
| `lan` ★ | `false` | `true` = other devices on the network may open the pages (needs `lanPin`) |
| `lanPin` | `""` | PIN (6+ characters) for full control from other devices; never sent to the pages |
| `lanViewPin` | `""` | optional, different PIN for look-only screens (every change refused) |
| `bracketCacheSeconds` | `5` | how long one whole-bracket fetch is shared between pages (raise it for big brackets) |
| `maxBracketPages` | `16` | pages of 25 sets read per refresh (16 = 400 sets; the window warns when the bracket is bigger) |

The last six are for LAN events and big brackets: `guides\06 LAN and multi-TO events.html`. They are read at
start: restart the dock after changing them.

## What OBS reads (`output\`)

Same file names as the Stream Updater app, so an existing Stream Updater scene can be repointed instead of
rebuilt. `tools\obs\make_obs_scenes.py` builds a ready scene collection that uses them.

| File | Content |
|---|---|
| `overlay.png` | the active theme's `overlay.png` (else Default's), copied whenever the theme or the file changes |
| `player1_tag.txt` / `player2_tag.txt` | name as shown ("PREFIX \| Tag", shortened to fit the name box) |
| `player1_pfp.png` / `player2_pfp.png` | start.gg picture, circle-cropped (else `assets\default.png`) |
| `player1_stock.png` / `player2_stock.png` | the stock icon for the picked character + colour (blank if none) |
| `match_round.txt` | round name (the theme's wording when a theme with round names is on) |
| `player1_name.txt`, `player*_score.txt`, `player*_character.txt`, `player*_color.txt`, `game_count.txt`, `player*_image_url.txt` | extras for your own layouts (not used by the generated scene) |

## Themes

The theme list in ⚙ is every folder with a `theme.json` in the themes folder (`Default`, `Halloween`, `Winter`
in this package). Pick one, then tick **Themed round names** (start.gg's round names replaced by the theme's,
everywhere: dock pages, `match_round.txt`) and/or **Themed overlay graphic** (its `overlay.png` goes to OBS).
An orange badge in the header shows a theme is on. How to make one: `tools\render\overlays\melee_themes\PROVIDE YOUR OWN.md`.

## Setup log (for the VODs)

Every Put on stream / Put on setup / report writes `timestamps\<tournament-slug>\setups.jsonl` (plus
`setups.csv` and `Setup times.txt` for people). After the night copy that folder and the recording to the SSD
(`guides\02 Weekly workflow.html`, "After the night"). Format: `docs\reference\RENDER_PC_HANDOFF.md`.
