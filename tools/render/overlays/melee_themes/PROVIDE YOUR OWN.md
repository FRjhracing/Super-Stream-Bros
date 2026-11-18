# Melee overlay themes: provide your own art and font

This folder is the **one place for the Melee stream look**, read by three tools:

- the **Melee dock** (`tools\render\docks\melee\`): copies the active theme's `overlay.png` to its `output\`
  for OBS, renames rounds with the theme's `rounds`, and sizes long names to `name_box`;
- the **OBS generator** (`tools\obs\make_obs_scenes.py`): places every OBS source from `layout.json`;
- the **VOD renderer** (`vod_overlay.py`): rebuilds the side panel on rendered sets so VODs look like the stream.

The package ships **generic samples** (`Default\overlay.png` = a blank panel with empty bars and slots where the
text and pictures go, `Default\default.png` = a plain picture) and two example themes made from them by
`make_theme_art.py` (`Halloween\`, `Winter\`). Replace them with your stream's art.
`guides\04 Overlay layout map.html` shows which file fills which spot; `guides\05 Stream PC dock and OBS.html`
shows the dock and OBS side.

```
melee_themes\
  layout.json                    optional: your positions (copy examples\melee_layout.example.json)
  make_theme_art.py              draws a seasonal version of YOUR Default\overlay.png (Pillow)
  Default\
    overlay.png                  your stream's side panel (sample included)
    default.png                  picture for players without one (sample included)
    theme.json                   {"name": "Default"}
    <your font>.otf / .ttf       optional, VOD renders; set "font_file" in layout.json (missing = Segoe UI Bold)
  <ThemeName>\                   seasonal looks, e.g. Halloween\, Winter\, Anniversary\
    theme.json                   name + round names (required: the dock lists folders that have one)
    overlay.png                  optional, same size as Default's (missing = Default's is used)
    art.json                     optional, settings for make_theme_art.py
    overlay_layers\              make_theme_art.py's pieces, to touch up in an image editor
```

## `overlay.png` (the side panel)

The renders and the generated OBS scene lay it out on a 1920x1080 frame like this (PROTOCOL's stream; for a
different layout put your numbers in `layout.json`, then `python tools\render\make_sample_assets.py --force`
redraws the blank sample to match and `python tools\obs\make_obs_scenes.py --force` rebuilds the OBS scene):

| Element | Position (px, 1920x1080) | layout.json |
|---|---|---|
| panel | x 0..607, full height: your PNG is scaled to 607 px wide (PROTOCOL's master is 3638x6482, i.e. 6x) | `panel_w` |
| webcam box | 16,37 size 580x326: leave it **transparent** (stream sets show the webcam through it; rendered sets get a "REPLAY" card) | `cam` |
| player 1 name | right edge x 452, centre y 631 (OBS box 273x59); picture 488,590 77x77; stock icon 540,627 47x47 | `p1`, `name_box` |
| player 2 name | right edge x 455, centre y 737; picture 488,698 79x79; stock icon 540,750 47x47 | `p2` |
| round text | centred on x 303 (bar x 43..563), centre y 846 (OBS box 520x64) | `round`, `round_box` |
| game | x 607..1920, full height | `game_x`, `game_w` |

Keep a strip at the bottom of the panel free if you want seasonal scenery there (`make_theme_art.py` draws from
under the round bar to the bottom by default).

## Font

VOD renders: `"font_file"` from `layout.json` (looked up in `Default\`, this folder, then the Windows font
folders). Without it, or if the file is missing, a standard Windows font is used (Segoe UI Bold, else Arial
Bold) and the render prints a note. OBS: an installed font, named in `"obs_font"`. The dock: the font file in
`tools\render\docks\melee\assets\fonts\`. Free, licence-clear fonts: [Google Fonts](https://fonts.google.com/).
(PROTOCOL's own stream uses "Typo Round Regular Demo", which is not included.)

## Stock icons and the default picture

Taken from the Melee dock's art folder: `tools\render\docks\melee\assets\stock_icons\<color> <Character>.png`
(e.g. `red Falco.png`, `neutral Captain Falcon.png`; the full list of 123 names is in that folder's
`PROVIDE YOUR OWN.md`) and `assets\default.png` (shown when a player has no start.gg picture; a plain sample is
included). The stock icons are Nintendo art and are not packaged.

## `theme.json` (seasonal looks)

```json
{
  "name": "Halloween",
  "finalsLabel": "Final Haunt",
  "finalsFrom": 4,
  "rounds": {
    "Winners Round {n}": "Survivors Round {n}",
    "Winners Final": "Survivors Final",
    "Losers Top 8": "Graveyard Top 8",
    "Grand Final": "Grand Fright"
  }
}
```

- `name`: shown in the dock's theme list and header badge.
- `rounds`: start.gg round name -> name on stream; `{n}` = round number; `"Losers Top 8"` = the losers round
  with 4 players left (the dock finds it from the bracket). Names not listed stay as they are.
- `finalsLabel` / `finalsFrom` (4 or 8): label on the last rounds in the dock's Full Bracket page.
- Leave `rounds` out for a theme that only changes the graphic.

### Using a theme

- **On stream**: dock ⚙ > **Seasonal theme** > pick it. Tick **Themed round names** and/or **Themed overlay
  graphic**. An orange badge in the dock's header shows it is on; OBS shows the new `overlay.png` right away
  (and the dock re-copies it when the file changes, checked at every bracket refresh, so edits saved from an
  image editor reach OBS within about 20 s). Pick
  **Default** again after the event.
- **In VODs**: `"season": "<ThemeName>"` in that week's `vod_config.json` (off-stream sets get the theme's
  panel and round names; no losers-top-8 detection there).

## `make_theme_art.py` (seasonal art from your own panel)

```
python tools\render\overlays\melee_themes\make_theme_art.py Halloween
python tools\render\overlays\melee_themes\make_theme_art.py Winter
python tools\render\overlays\melee_themes\make_theme_art.py Spooky --base "D:\art\panel.png"
```

Reads your `Default\overlay.png` (never changes it) and `layout.json`, and writes `<Theme>\overlay.png`,
`<Theme>\overlay_layers\NN_*.png` (each piece as a full-size transparent layer, to adjust in paint.net, GIMP or
Photoshop: import them in number order over your panel) and `Preview_small.png`. A `theme.json` with example
round names is written if the folder has none. Kits: `halloween` (tint, moon, bats, graveyard, fog,
jack-o'-lantern) and `winter` (tint, snowy ground, trees, snowflakes). Every piece is placed in fractions of a
"scene" box (default: under the round bar to the bottom of the panel), so it follows your layout. `art.json`:

```json
{
  "kit": "halloween",
  "scene": [0, 900, 607, 1080],
  "tint": [40, 0, 70, 80],
  "pumpkin": [400, 1000, 70, 56],
  "seed": 57
}
```

`scene` x1, y1, x2, y2 and `pumpkin` cx, cy, w, h are in 1920x1080 stream pixels; `tint` is r, g, b, alpha
(`[0,0,0,0]` = none); `pumpkin: false` leaves it out; `seed` changes the random bits. A new kit is one
function in the script (see `kit_winter`).
