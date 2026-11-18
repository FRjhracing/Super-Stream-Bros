# Ultimate VOD scoreboard ★

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

A top scoreboard laid over the Ultimate recordings (16:9 gameplay underneath): two player plates (picture, name,
score box, a line under the name, W/L mark) and a logo in the middle. Everything here is a **generic sample**;
make it yours with your own colours, logo and font. See `PROVIDE YOUR OWN.md` and `guides\04 Overlay layout map.html`.

| file | what |
|---|---|
| `layout.json` | every position, size, colour, glow and font size (1920x1080 px). The one place to change the look. |
| `make_frame.py` | builds `frame.png` (the empty scoreboard) + `frame_layers\` from layout.json and `emblem.png`. **Needs Pillow**; re-run after editing layout.json or the emblem. `--glow r,g,b,alpha` = a one-off glow colour. |
| `frame.png` | the built frame (sample), so rendering doesn't need Pillow |
| `frame_layers\` | 01 glow, 02 plates, 03 bars, 04 emblem (full canvas each, for an image editor) + Preview.png |
| `emblem.png` | centre logo (sample: "YOUR LOGO") |
| `ultimate_overlay.py` | **stdlib + ffmpeg**: `build_overlay(png, state)` fills in a set; `overlay_video(video, [(start, end, png)], out, trim=, gain_db=)` burns it onto a recording |
| `fonts\` | your font (.otf/.ttf); empty = Segoe UI Bold |
| `default_pfp.png` | picture when a player has none (sample) |

## State (what the cutter passes per set)
```json
{"p1": {"prefix": "TEAM", "tag": "Player One", "score": 2, "mark": "W", "imageUrl": "https://images.start.gg/..."},
 "p2": {"tag": "Player Two", "score": 1, "mark": "L"},
 "round": "Grand Final", "bestOf": 5}
```
- Under P1's bar: `round`. Under P2's bar: `Best of N`. Override either with `pN.sub`.
- `score` empty/None = empty score box (shown when the order of game winners isn't known).
- `mark` = W/L under the score box (grand finals).
- Names: "prefix | tag" shrunk down to 70% size, else tag only down to 50%, else cut with "…".
- The overlay is a still per state; score changes are separate `(start, end, png)` windows.

ffmpeg is found at `tools\ffmpeg\bin\`, else `PROTOCOL_FFMPEG` / `PROTOCOL_FFPROBE`, else PATH.
Encoder default `h264_amf` (AMD); pass `encoder="libx264"` (or change it) without an AMD GPU.
