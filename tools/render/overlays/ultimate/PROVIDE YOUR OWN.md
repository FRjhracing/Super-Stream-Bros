# Ultimate scoreboard: provide your own art and font

Included: the code (`ultimate_overlay.py`, `make_frame.py`), the layout (`layout.json`) and **generic samples**
(`emblem.png` "YOUR LOGO", `default_pfp.png`, `frame.png` + `frame_layers\` built from them). Renders work as is.

To use your own look:
- `emblem.png`: your centre logo (transparent PNG, any size; drawn `logo.width` px wide). Then rebuild the frame:
  `python tools\render\overlays\ultimate\make_frame.py` (needs Pillow).
- `layout.json`: positions, sizes and colours of every box (see the README here and `guides\04 Overlay layout map.html`).
- `fonts\`: put your font file here (.otf or .ttf). Without one, a standard Windows font (Segoe UI Bold) is used.
- `default_pfp.png`: picture for players without a start.gg picture.
- `char_art\`: filled automatically: `ultimate_cutter.py` downloads start.gg's character renders for the
  thumbnails on first use (not packaged).
