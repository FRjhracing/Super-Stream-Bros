# Stream PC: finishing this package

This package was assembled on the render PC on 2026-11-17 and finished on the Stream PC on 2026-11-18. Same
rules as the rest: **no third-party software, fonts or overlay art** in the package (links + install steps
only), no secrets (`STARTGG_TOKEN`, Slippi `playKey`, OAuth tokens, `dock_config.json` with personal settings).

## 1. Add the docks (source only)

- [x] `tools\render\docks\melee\` <- `Super Stream Bros Melee\`: `dock_server.py`, `static\`, `start_dock.bat`,
      `open_docks.bat`, `set_token.bat` (only asks for the token), `README.md`. Left out: `output\`, `timestamps\`,
      `dock_state.json`, `dock_config.json`, `player_prefs.json`, `setup_state.json`, `__pycache__`, the stock
      icons and the stream font (`assets\stock_icons\PROVIDE YOUR OWN.md` lists all 123 file names;
      `assets\fonts\PROVIDE YOUR OWN.md`). `assets\default.png` = the generic sample picture.
      Made generic in the package copy (the Stream PC's live dock is unchanged): `shortLink` empty by default
      (set in `dock_config.json`; written on first start), themes folder = `tools\render\overlays\melee_themes`
      (setting `themesFolder`), stream font = any file in `assets\fonts\`, OBS name box from `layout.json`
      (`name_box`), port override `SSB_MELEE_DOCK_PORT`, "Use latest (series link)" label, missing stock icons
      show the name instead of a broken image.
- [x] `tools\render\docks\ultimate\` <- `Super Stream Bros Ultimate\` the same way (zip steps in its
      `README.md`). `player_characters.json` left out (real players' data); `characters.json` included.
      `shortLink` empty by default, generic labels in `SETUP.txt`.
- [x] Placeholder `tools\render\docks\README.md` replaced.

## 2. Bring the formats up to date

- [x] `docs\reference\RENDER_PC_HANDOFF.md` replaced with the Stream PC's copy.
- [ ] `clock_mark` event: not built in the Melee dock (no change planned as of 2026-11-17); document it there
      and in `docs\Strategy.md` section 7 if it is ever added.

## 3. Stream-side docs

- [x] OBS: `tools\obs\make_obs_scenes.py` builds the scene collection from `layout.json` (sources reading the
      dock's `output\`: overlay, names, pictures, stock icons, round; plus "SSB No Overlay"); tested by importing
      into OBS 33. Recording settings, screenshots of the preview and the source list: `guides\05`.
- [x] How to add the docks in OBS (Custom Browser Docks, ports 8765 / 8766): `guides\05`, dock READMEs.
- [x] Seasonal themes: how the dock picks one (⚙ > Seasonal theme) in `melee_themes\PROVIDE YOUR OWN.md` and
      `guides\05`; `make_theme_art.py` draws a theme from your own panel and layout (examples `Halloween\`, `Winter\`).
- [x] The handoff by hand: `guides\05` "After the night", `guides\02` updated.
- [x] Wii / Slippi Nintendont and flash drive labelling: `guides\05` section 6.

## 4. Check before sharing

- [x] `START HERE.html` opens and every link works (checked 2026-11-18).
- [x] Searched the package for tokens/keys: only documentation and code that reads `STARTGG_TOKEN` hit.
- [ ] Run `python tools\python\ssb_autopilot.py <N> --plan-only` against a past week from the package folder
      (after installing the third-party tools per `guides\01`) to prove the copy works. Render PC job.
- [ ] Render PC: `guides\images\melee_sample_frame.png` / `melee_sample_panel_rendered.png` were rendered before
      the sample panel fix (the faint "SAMPLE OVERLAY" mark punched see-through holes in the panel and sat at the
      bottom; it is now blended and sits between the webcam and the names). Re-render them with `vod_overlay.py`.
