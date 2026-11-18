# Stream font: provide your own (optional)

Put the font your overlay uses for player names here (one `.otf` or `.ttf`; the first one in A-Z order is
used). The dock measures names with it so it knows when a long name ("PREFIX | VeryLongTag") would shrink
too far in OBS's name box: it then drops the prefix, or cuts the tag with "…" (see `name_box` in
`tools\render\overlays\melee_themes\layout.json`).

Without a font file the dock measures with Segoe UI, which is close enough for most rounded sans fonts.

The font file here is only for measuring. OBS draws the text with an **installed** font: install the same font
in Windows (right-click > Install for all users), then put its name in `layout.json` (`"obs_font"`) before
running `tools\obs\make_obs_scenes.py`, or pick it in each OBS text source's Properties.

No font is included (PROTOCOL's stream font is a commercial demo font). Free, licence-clear options:
[Google Fonts](https://fonts.google.com/) (for example Nunito, Varela Round or Baloo 2 for a rounded look).
