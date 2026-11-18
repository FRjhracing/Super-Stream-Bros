# OBS scene collection generator

`make_obs_scenes.py` writes an OBS scene collection that shows the Melee dock's overlay files at the positions
in `tools\render\overlays\melee_themes\layout.json`, the same file the VOD renderer uses, so the stream and
the rendered VODs line up. Standard library only. Tested by importing into OBS 33.

```
python tools\obs\make_obs_scenes.py
python tools\obs\make_obs_scenes.py --name "My Weekly" --dock "D:\Docks\melee" --force
```

| Option | Default |
|---|---|
| `--name` | `Super Stream Bros` (the collection's name in OBS) |
| `--themes` | `tools\render\overlays\melee_themes` (reads `layout.json` there) |
| `--dock` | `tools\render\docks\melee` (OBS reads its `output\` folder: absolute paths are written, so run it again if you move the dock) |
| `--output` | the overlay folder itself, when OBS reads it from elsewhere, e.g. a hub's share `\\192.168.1.10\ssb-melee` (`guides\06 LAN and multi-TO events.html`) |
| `--out` | `tools\obs\generated\` |
| `--force` | overwrite earlier output |

It writes `<name>.json` (import it) and `<name> layout.svg` (open in a browser: every source's box over your
panel art).

## Import

1. OBS > **Scene Collection > Import** > `...` > pick the `.json` > tick it > **Import**.
2. **Scene Collection > <name>** to switch to it.
3. Double-click **Game capture** and **Webcam**: pick your capture card and camera (left empty on purpose;
   devices differ on every PC). Add your audio (capture card audio, mics) with **+** in Audio Mixer / Sources.
4. Start the dock once so `output\` exists; the overlay and names then show up.

## Scenes and sources

**SSB Stream** (bottom to top): Game capture (fitted into `game_x`/`game_w`, full height), Webcam (`cam` box),
Overlay (`output\overlay.png` stretched to `panel_w` x 1080), P1/P2 name (`playerN_tag.txt`, right-aligned in
`name_box` at `name_right`/`name_cy`), P1/P2 picture (`playerN_pfp.png` in the `pfp` square), P1/P2 stock icon
(`playerN_stock.png` in the `stock` square), Round (`match_round.txt` centred in `round_box`).

**SSB No Overlay**: the game capture, full screen (for breaks or a clean feed).

Text uses `obs_font` / `obs_font_bold` / `text` from layout.json (default Segoe UI Bold, white). Install your
stream font in Windows first and put its name there, or change it in each text source afterwards. Every key:
`examples\melee_layout.example.json`.

## Recording settings the render PC relies on

Settings > Output > Recording: **Hybrid MP4** (or MKV), path on the SSD `MeleeRecordings\`; Settings >
Advanced > Recording: file name format **`%CCYY-%MM-%DD %hh-%mm-%ss`** (the cutter reads the start time from
it). Video 1920x1080. Details and screenshots: `guides\05 Stream PC dock and OBS.html`.
