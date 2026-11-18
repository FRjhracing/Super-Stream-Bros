# Slippi Tournament Tools: Project Notes

> **Paths moved 2026-11-11 (desktop copy):** render sources now live in `tools\render\`:
> `Seasonal\` -> `tools\render\overlays\melee_themes\`, `UltimateOverlay\` -> `tools\render\overlays\ultimate\`,
> `tools\StreamDock\` -> `tools\render\docks\stream_dock\`, `Ultimate Dock\` -> `tools\render\docks\ultimate_dock\`,
> `tools\slippi-playback\` -> `tools\render\slippi_playback\`, `ChannelArt\` -> `tools\render\art\channel\`,
> `TournamentPage\` -> `tools\render\art\tournament_page\`. Older entries below use the old paths. The stream
> laptop's copy keeps `StreamDock\` and `Seasonal\` at the top (OBS reads them there).
> **Deleted 2026-11-11** (user cleanup after Lucky Stats): all local replays and Lucky Stats folders up to #59
> (incl. the `_format_sample` set), `_archive\obs_backup\`, `_archive\Protocol #57 VOD text\`, the #59 fix
> archives' replay copies. Entries that mention them are marked "(deleted)".
>
> **2026-11-11: local replays live on the SSD**: `slippi_uploader.py` copies each flash drive to `<SSD>\Protocol VOD\Melee\Protocol #N\replays\<setup>\`, says the drive can be pulled, then uploads that copy to `gdrive:Protocol #N/<setup>` in the background (log `replays\upload_<setup>.log`; waits + retries at the end; no SSD = direct upload as before; the SSD is never offered as a flash drive). `vod_cutter.py` reads `"replays"` (default `replays`, next to the config). `Local Replays\` on D: is no longer used.
> **2026-11-11: all Python scripts moved to `tools\python\`** (from the top level and `tools\`); run e.g. `python tools\python\vod_cutter.py`. Older entries use the old script paths.
> **2026-11-11: tournament folders moved to the SSD.** `Recording-OUT\<t>\` + `Recording-IN\<t>\` (dock logs) -> `<SSD>\Protocol VOD\Melee|Ultimate\Protocol #N\` (dock logs in its `dock\`); `Recording-IN|OUT|BACKUP` on D: removed. Configs: `{ssd}` = the SSD's drive, relative paths next to the config; with the config on the SSD the videos go next to it (no media_dir). #58 Melee's raw recording was deleted (videos on YouTube).

Weekly workflow for the Protocol Melee tournament series: get replays off the setup flash drives into Google Drive, then (experimental) link them to start.gg sets and build per-player stats input.

_Last updated: 2026-10-25 (Seasonal themes + Halloween art done for #57; stream laptop sessions 2026-10-19..21; see README.md for layout and weekly steps)._

## Stages

| # | Stage | Status |
|---|-------|--------|
| 1 | **Upload**: plug in drives, replays go to Drive | Working, used on #54 and #56 |
| 2 | **Scan**: inventory every replay (stage, chars, ports, winner, timing) | Working, 40 Nintendont replays on #56 |
| 3 | **Match**: group games into sets, match to start.gg sets, drop handwarmers/friendlies | Working inside `vod_cutter.py` (`match_sets`), correct on all #56 sets |
| 4 | **Export** for Lucky Stats: `tools/luckystats_export.py` -> `LuckyStats\<tournament>\sets\set-<startgg set id>\` (01.slp.. + context.json) | Done for #57 (21 sets) and #58 (22) on 2026-11-04 |
| 5 | **One front end** (GUI/launcher chaining 1-4) | Not started |
| - | **VOD Cutter** (full VOD + per-set videos) | Working, #56 rendered and uploaded; see `VODCUTTER_PROJECT_NOTES.md` |
| - | **Stream Dock** (OBS docks: bracket + overlay) | Used live on #56; bracket overview added 2026-10-20 |
| - | **Ultimate Dock** (Ultimate TO: bracket + recording timestamps) | Built 2026-10-26, first use #57 |

## Stream Dock (`StreamDock\`)

Goal: manage the bracket and the stream overlay from one OBS dock instead of browser + Stream Updater + OBS.

- `start_dock.bat` runs `dock_server.py` on `http://127.0.0.1:8765/` (localhost only). In OBS: Docks > Custom Browser Docks, add that URL.
- Token: read from `STARTGG_TOKEN` (process env, then HKCU\Environment). Never sent to the page or written to disk. API calls need header `X-Dock: 1` and a localhost Host header.
- Tournament: follows https://www.start.gg/ProtocolSOVA (307 redirect to `/tournament/<slug>`), unless a slug is pinned in settings. **Only Melee events** are used (videogame id 1); Protocol always also has an Ultimate event, which is ignored.
- Bracket: open sets (call order, live first) with Put on stream / Call / Start / Report (score or DQ); recent results with Reset. "Put on stream" loads the overlay, assigns the tournament's first start.gg stream (if one exists) and marks the set in progress. Polls every 20 s.
- Overlay: writes the same files as Stream Updater to `StreamDock\output\`. Profile pictures are circle-cropped in the page (canvas, via a same-origin image proxy limited to images.start.gg). **Bug on #56 (fixed 2026-10-20):** the page loaded `/api/img` with a plain `<img src>`, which can't send the required `X-Dock` header, so the server answered 403 and every player got the default avatar. The page now `fetch`es the image with the header and draws it from a blob URL. Character/color per player tag is remembered in `player_prefs.json`.
- OBS: scene collection **"Protocol Dock"** = copy of "Protocol" with the 7 Stream Updater sources repointed to `StreamDock\output\`. Fallback: switch back to "Protocol" and use Stream Updater. Backup of the original: `_archive\obs_backup\Protocol.json`. (deleted 2026-11-11)
- **Bracket overview** (added 2026-10-20): `http://127.0.0.1:8765/bracket`, a second OBS custom browser dock (or the ⊞ button in the main dock opens it as a window). Whole Melee event by round (winners/losers rows for double elim, round columns for round robin, tabs for pools), set letters, Waiting/Called/Playing/LIVE/Done/DQ, other streams, stations, "Winner of B"/"Loser of C" for empty slots. Click a set for the same actions as the main dock. start.gg hides "X vs bye" sets, so the server looks those up by ID and follows the chain to the visible source (`resolve_byes`). Shared page code is in `static/common.js` (actions, putOnStream, report/confirm dialogs, pictures, themes).
- Future sets (not both players assigned) show no status badge in the overview, only "Winner of X"/"Loser of Y".
- Top-3 seeds (2026-10-21): waiting sets (state 1/4/7, both players known) with an entrant whose start.gg `initialSeedNum` ≤ 3 get a gold outline (`--seed`, independent of the theme) in both docks; tooltip names the seed. Shared `markTopSeed()` in common.js.
- **Slow docks 2026-10-21 = flaky IPv6, not the dock.** One of start.gg's IPv6 addresses intermittently didn't answer on the laptop's network; Python waits the full 20 s timeout per address before trying IPv4, so `/api/sets` took 20-60 s while browsers (fast fallback) and start.gg itself were fine. Fix: `dock_server.py` and `vod_cutter.py` sort IPv4 addresses first (`socket.getaddrinfo` wrapper). Same queries went from 21-42 s to 0.4-1.7 s. Test script idea: connect to each address of api.start.gg with a 5 s timeout.
- Sync between the two docks: server `version` counter, bumped on overlay/action/theme/stream/tournament changes; pages long-poll `GET /api/changes?since=N` (returns within ~25 s or on change). start.gg results are cached 5 s so two docks don't double API calls; actions clear the cache. `?nowatch` disables the long-poll (needed for headless screenshot tests, which otherwise never finish).
- "LIVE" badge = only the set currently on our stream (the overlay's set). Other started sets show "Playing"; sets on other people's streams show that stream's name. Our stream is picked once in ⚙ (`streamId` in `dock_config.json`).
- Themes: presets + custom accent/panel colors in ⚙, saved in `dock_config.json` (`theme`).
- The page reloads itself when files in `static\` change (`uiVersion` = newest mtime), so UI edits don't need an OBS restart. Server (`dock_server.py`) edits still need `start_dock.bat` restarted.
- `start_dock.bat` uses `%LOCALAPPDATA%\Programs\Python\Python314\python.exe` directly (the `python` on an old PATH is the Microsoft Store stub).
- 2026-10-19: user tested on a private start.gg test tournament ("SuperStreamBros"): put on stream, call, start, report, DQ, reset and grand-final reset all worked.
- Mutations used (all tested): markSetCalled, markSetInProgress, assignStream, reportBracketSet (gameData: loser's games first, then winner's), resetSet (resetDependentSets false).

## Ultimate Dock (`Ultimate Dock\`; built 2026-10-26 for the Ultimate TO's machine)

- Self-contained copy of the Stream Dock idea for the Ultimate side, zipped as `Ultimate Dock.zip` and sent to the Ultimate TO. Everything (server, pages, `SETUP.txt`, `start_dock.bat`, `set_token.bat`) lives in that folder; it shares no code with `StreamDock\` (edit both if a shared fix is needed).
- Recording only: no overlay files, characters, pictures, themes or seasonal code. Their main OBS hosts the dock (`http://127.0.0.1:8766/`, bracket overview `/bracket`) and records "Stream 1"; a portable OBS records "Stream 2". Port 8766 so it can run next to the Melee dock (8765).
- Events: start.gg videogame id **1386** (Ultimate) only, singles first. Follows start.gg/ProtocolSOVA once per server start unless a slug was pinned with "Load slug" (`pinSlug` in `dock_config.json`); the Melee dock instead stays on its saved slug.
- **Timestamps**: set cards have "Put on stream 1" / "Put on stream 2" (plus Call/Start/Report). Each click logs an event, then marks the set in progress on start.gg (and assigns a start.gg stream if one is picked in ⚙ per recording; optional). Per recording: "● Rec started" (press when that OBS starts recording; video times count from it), "★ Mark", "■ Set over". Ends are also logged when the next set goes on the same stream, a set moves streams, the set is reported in the dock, or the poll sees it reported on start.gg (uses `completedAt`). Rows can be deleted (✕) for mis-clicks.
- Output in `timestamps\<slug>\`: `log.jsonl` (source of truth), `timestamps.csv` (UTF-8 BOM for Excel), `Stream 1 chapters.txt` / `Stream 2 chapters.txt` (video time from Rec started + clock time). Fallback if Rec started wasn't pressed: OBS's default file name = recording start time.
- start.gg "preview_..." set ids (bracket not started) change when the bracket starts; the dock matches the set on a recording by id or by set letter + both entrant ids and updates the id.
- Tested 2026-10-26 on the laptop against PROTOCOL #57's Ultimate event (read-only; logging tested with `state: 2` so no start.gg changes were sent; report detection tested offline). Not yet tested: real reporting/mutations on an Ultimate bracket, OBS on the TO's PC.
- Encoders on the TO's PC (user's plan 2026-10-26): main OBS (hosts the dock, Stream 1) = x264 CPU, portable OBS (Stream 2) = GPU encoder, so the two recordings don't share an encoder. The stream laptop will **not** dual-record going forward (the replay renders cover Melee off-stream sets); `PortableOBS\` here (`Desktop\OBS Portable Start.lnk`, records to `Videos\2ND OBS OUT`) was a dock test only.
- Later: feed the timestamps into a VOD cutter run for the Ultimate recordings (no replays, so cut purely from the log).

## Seasonal themes (`Seasonal\`; built 2026-10-24, first used for Halloween / PROTOCOL #57 on 2026-10-26)

- **Layout**: one folder per look in `Seasonal\` (user wants more later: Christmas, anniversaries, a #75 special). Each has `theme.json` (`name`, optional `rounds`, `finalsLabel`, `finalsFrom`) and optional `overlay.png` (3638x6482, same as Default). `Default\overlay.png` = the everyday overlay, **moved 2026-10-24 from `%USERPROFILE%\Pictures\protocoloverlaynew_26x.png`**. How to add a theme: README.
- **Dock**: ⚙ > Seasonal theme (list = folders with theme.json) + checkboxes "Themed round names" / "Themed overlay graphic"; orange badge in the dock header while a theme is on. Config keys `season`, `seasonRounds`, `seasonOverlay` in `dock_config.json`. Left on **Halloween** after 2026-10-24 testing; switch to Default after #57.
- **Overlay image switch**: the dock copies the active theme's `overlay.png` (else Default's) to `StreamDock\output\overlay.png`; OBS "Protocol Dock" > source "Overlay" reads that file. Fallback collection "Protocol" reads `Seasonal\Default\overlay.png` directly. OBS backups: `_archive\obs_backup\2026-10-24_before_seasonal\`. (deleted 2026-11-11)
- **Round names**: applied server-side in `simplify_set` (`round` = themed, `roundPlain` = start.gg's), so the main dock, the bracket overview and `match_round.txt` all match. `{n}` keys match round numbers; `"Losers Top 8"` = losers round with 4 left, found from `phaseGroup { rounds { number } }` (Losers Final = lowest number; top-8 round = +3). The overlay state keeps `roundPlain`/`losersTop8`, so switching theme re-labels the round already on stream. Any start.gg-style name in the round box ("Winners Final", typed or left over from before) is themed too (`STARTGG_ROUND`, `Dock.theme_round`); other typed text ("Pools Top 2") is left alone.
- **Finals label**: bracket overview tags column headers with `finalsLabel` ("Final Haunt") for top 4 (Winners Final, Losers Semis/Final, Grand Final(s)); `finalsFrom: 8` widens it to top 8. User asked for top 4 (top 8 covered almost the whole test bracket).
- **Halloween names**: Winners = "Survivors ...", Losers = "Graveyard ...", Grand Final = "Grand Fright"; edit in `Seasonal\Halloween\theme.json`.
- **OBS round text**: `match_round.txt` in "Protocol Dock" now has a 520x64 fit-to-bar box at 43,812 (scale to inner bounds, centred), so long names shrink instead of running past the round bar (before, "Winners Quarter-Final" overflowed by ~110 px). Verified in OBS 2026-10-24.
- **VOD Cutter**: `vod_overlay.py` uses `Seasonal\Default\overlay.png`; optional `"season": "Halloween"` in `vod_config.json` gives off-stream sets the theme's overlay and round names (no losers-top-8 detection there).
- **Halloween art** (`Seasonal\Halloween\`): the **finished banner is the user's `banner_layers\HalloweenBanner.pdn`** (2026-10-25; built on our layers; logo/frame blue hue-shifted to purple, outer glow recolored purple (78,40,247)). Measured shift: HSV hue +72 deg, saturation x0.95, value x0.822, only on the bright logo blue (dark background untouched). `make_halloween_art.py` (Pillow) makes the overlay: `overlay.png` + `overlay_layers\` 01-14 (01 panel darken = black 40% over the blue gradient only, keeps it blue; 02 purple glow around the whole protocol emblem; 03 purple logo; 04-10 graveyard: glow, moon, bats, ground, tree, tombstones, fog; 11-14 pumpkin: purple outer glow, stem, face glow, body = the banner's jack-o'-lantern redrawn 126x100 stream px left of the tags, mouth shows the panel). Overlay glows (emblem, pumpkin) = (165,115,255) at alpha 100, matched to the moon's glow strength (user 2026-10-25); constants `GLOW_PURPLE`, `PANEL_DARKEN`. v2 in `_archive\halloween_overlay_v2_2026-10-25\` + `Preview_small.png`. `--banner` also redoes `banner_layers\` 1-4 (never the .pdn). Layers are full canvas size for paint.net (Layers > Import from File in number order); re-running overwrites overlay layers. v1 overlay (orange-glow pumpkin, blue logo) in `_archive\halloween_overlay_v1_2026-10-24\`. Overlay free space: x 10-150 / y 590-790 (left of tags), y 880-1075 (under round bar), in 606x1080 stream px. The dock re-copies a theme's `overlay.png` when it changes on disk (checked on every bracket poll), so a paint.net save reaches OBS without a restart.
- Older banner draft (two pumpkins) stays in `TournamentPage\PROTOCOL 57\` (`Pumpkin_Overlay.png`, `make_pumpkin_overlay.py`) with the original `Banner.png`. start.gg's image host is blocked from the shell; the banner came via a browser download. The user edits the start.gg banner themselves.
- Events renamed for #57: "Melee Mash Singles" (Melee), "Ultimately Spooky Singles" (Ultimate).
- Venue perks this week: costume bonus = $2 off entry (judged by the TO and bracket opinion), only if that player doesn't DQ in bracket; +$5 payout bonus to any costume-bonus player who makes grand finals.
- `Seasonal\Default\no_overlay.png` = frame for the OBS scene "Protocol No Overlay" (moved 2026-10-24 from `Pictures\protocol_overlay3x.png`; both collections repointed, backups in `_archive\obs_backup\2026-10-24_before_no_overlay_move\`). Not switched by themes. Only remaining outside link: the stream font `Typo_Round_Regular_Demo.otf`, installed per-user. (deleted 2026-11-11)

## Stage 1: Upload (`slippi_uploader.py`)

Run: `python slippi_uploader.py "Protocol #54"`, then plug in drives one at a time.

- Destination: Google Drive folder `SSBM Replay Storage` (folder ID `1Ci2mBwQCtmCgsiAnqH73GAnOxrJnzZHN`). Each tournament gets a subfolder (`Protocol #50`, `#51`, ...). Existing folders: GCC STLS, Protocol #50-#53, StreamUpdater.
- Each drive uploads to `<tournament>/<folder name>/`. Folder name defaults to the drive's **volume label** (no drive letter) and can be overridden at the prompt. Choices are saved in `slippi_uploader_config.json` next to the script. Setup One's drive label is `SETUPONE` and is saved as "Main Setup".
- Drive identity is the **volume label**, not the drive letter and not the serial number (the flash drives have duplicate serials, which caused a bug earlier).
- If a drive has a `Slippi` folder at its root, only that folder is uploaded.
- Uses `tools\rclone\rclone.exe` (falls back to next to the script, then PATH). `--ignore-existing`, so re-plugging a drive is safe.
- Prompts "Press Enter for next drive / q to finish" after each successful upload.

### rclone setup (done once; redo if the config is lost)
- Remote must be named exactly **`gdrive`**, type `drive`, scope 1 (full access).
- Set `root_folder_id` to the folder ID above. It is an advanced option and is skipped if you answer "no" to advanced config. Set it afterward with `rclone config update gdrive root_folder_id <ID>` (the remote must already be named `gdrive`).
- During setup rclone asked about a Shared Drive and the answer "y" produced a remote called `gdrive SlippiDrive`. It was renamed to `gdrive` in the `rclone config` menu (`r`). `team_drive` is empty, which is correct since the folder lives in My Drive.
- Check with `rclone lsd gdrive:`: it should list the Protocol folders.
- rclone prints a notice that the shared Google client_id is being retired during 2026. Harmless now; if auth breaks later, create your own client ID (rclone docs: "Making your own client ID").
- Windows tip: from the project root run rclone as `.\tools\rclone\rclone`.
- Verified 2026-10-19: `lsd gdrive:` lists GCC STLS, Protocol #50-#54, StreamUpdater.

## Stage 2: Scan (`slippi_scan.py`)

Run: `python slippi_scan.py "<folder with one subfolder per setup>"`; writes `replay_inventory.json` and `.csv` to `<folder>\_scan`.

Records per game: stage, characters, ports, connect codes / display names / nametags, final stocks and percent, winner, duration, Slippi match ID + game number (netplay only), start time, `rel_start_s` (seconds since the first replay on the same setup) and `gap_from_prev_s`. Flags: `short_game` (<30 s), `incomplete`, `not_singles`. Never modifies replays. No dependencies.

Verified against the Slippi Launcher replay viewer for one netplay replay (winner, stage, duration, time all agreed). **Not yet run on Nintendont/Wii replays.**

## What we learned about the files

- Slippi Launcher's `user.json` fields: `uid`, `connectCode`, `playKey`, `displayName`, `latestVersion`. **`playKey` is a credential: never share it or paste it into notes.** Only `connectCode` and `displayName` are relevant here.
- A `.slp` stores both players. Identity is the connect code in the Game Start block, not the port. So replays do not need splitting per player; only the `user.json` differs.
- Netplay replays include a match ID (e.g. `mode.direct-<timestamp>-1`) and game number, which group games into sessions exactly. Tournament replays from Wiis most likely lack both, and probably lack connect codes.
- Sample netplay replay: Slippi 3.19.1, FRJH#957 (Captain Falcon, port 1) vs BZIMM#99 (Yoshi, port 2), Final Destination, BZIMM won 3 stocks to 0, 129 s.
- Clocks: `startAt` in netplay replays is UTC (ends in `Z`). **Nintendont/Wii replays store `startAt` with no timezone: it is the Wii's local clock** (verified on #56). `slippi_scan.py` copies it into the `start_utc` column unchanged, so for console replays that column is actually local time; treat values without an offset as local. Wii clocks may be off (#56 Main Setup: ~29.5 s ahead of the laptop), but spacing between games on one drive is reliable.

## Tournament facts (for matching, Stage 3)

- Sets are always best of 5; about 90% start on Battlefield.
- **Friendlies** are mixed in with set games; the organizer can verify tournament vs non-tournament sets.
- A set sometimes starts with a **handwarmer** game that is not part of the Bo5 and must be ignored. start.gg's score for the set tells how many games it really had (3-1 means exactly 4 games), so trim from the end: the last N games of that pairing are the set.
- Only **winners, losers and grand finals** sets are captured, and only on **Setup One** (main setup). Higher seeds usually play there. Not every set exists in the replays.
- Players mostly stick to their mains; few switch characters mid-set. Player tags could be required in future to tell players apart.
- start.gg W-L must agree with the replays, and gives a rough time window.
- start.gg: https://www.start.gg/ProtocolSOVA always redirects to the latest Protocol tournament (use it to find the current event slug).
- start.gg admin token is available. **Keep it in an environment variable (`STARTGG_TOKEN`), never in a file or chat.** The event slug is still needed, e.g. `tournament/<slug>/event/<event>`.

## Findings 2026-10-19 (first scan on real Nintendont replays)

Scanned `%USERPROFILE%\Documents\Slippi` (159 replays, 0 unreadable). Local folder `P53` (Protocol #53, 85 games, all `played_on = nintendont`), subfolders `Main Setup (stream)` 31, `BZimm (Left)` 30, `BJH (middle)` 24:
- **No connect codes, no display names, no match IDs/game numbers.** Answers open question 2: console replays carry no Slippi identity.
- In-game **nametags** appear in only ~19% of player slots (full-width text, e.g. `ＨＵＬＫ`, `Ｖ`, `ＯＳＲＳ`). Not reliable alone.
- `startAt` metadata is present on every game (no mtime fallback needed).
- So player identity for Stages 3-4 must come from start.gg (set entrants) matched by character + order/timing, with nametags as a bonus signal.
- The third setup appears to be BJH's ("BJH (middle)"); its drive label is still unconfirmed.

## Open questions

1. **Lucky Stats**: no documentation found. Does it only need `user.json`'s connect code to pick "you"? Does it need a particular folder layout? (Sample `user.json` and `.slp` were provided; `pcrain/slippc` was checked and has no context-JSON concept; it is only a parser/analyzer.)
2. ~~Do the Nintendont replays contain connect codes?~~ Answered: no (see Findings). Player identity comes from start.gg sets matched to replays (as `vod_cutter.py` does). Lucky Stats export still needs a way to tag players.
3. Start.gg event slug for Protocol #54 (only needed to backfill older VODs).
4. Drive labels: known `SETUPONE` = "Main Setup", `BZIMM` = "BZimm Setup". `GRACE` = "BZimm's" (BZimm's setup on #56; Drive folder renamed from "BZIMMM").
5. Round robins (small turnouts like #56): sets can be on any setup, so Stage 3 matching can't assume "bracket sets only on Setup One".

## Planned design for Stages 3-5

- **Match**: group each setup's games by character pair + gaps; use start.gg score parity to trim handwarmers; align first replays against bracket order since clocks are unreliable; output a review file with a confidence per match before anything is exported.
- **Export**: one folder per player containing their sets' replays (hard links where possible to avoid duplicate storage) plus a `user.json` with their connect code and display name.
- **Front end**: a small launcher with buttons for Upload / Scan / Match / Export, built once the stages above work from the command line.

## Next steps

00. **2026-11-03 (desktop): #57 cleared, #58 + Ultimate folders ready.** #57's recording, set videos, Full VODs and `work\` were deleted (~80 GB; laptop still has the source recording). Upload kit, render logs and chapter files in `_archive\Protocol #57 VOD text\`. Replays (108 + repaired T game 3) and match data (plan.json, review.md, startgg.json, vod_config.json) moved to `LuckyStats\Protocol #57\` (see its README.txt); the Lucky Stats sample set moved to `LuckyStats\_format_sample (luckystats set 4540730)\`. `Local Replays\` is now empty, so Slippi Launcher no longer lists #57. (deleted 2026-11-11)
   - **#58 (2026-11-02)**: replays on Drive `gdrive:Protocol #58` (Main Setup, BIGGIE, BJH, BZimm's; 101 files, 310 MiB). Recording + **new Melee dock version** (more metadata for off-stream setups) still on the laptop. Drop: recording in `Recording-IN\`, dock files in `Recording-OUT\Protocol #58\dock\`. The new dock source isn't in this project copy yet (bring the laptop's `StreamDock\` over). New stick label BIGGIE.
   - **Ultimate #58**: new Ultimate Dock version (2 recordings, characters per player, start/end times for ALL venue sets from bracket data). Drop: recordings in `Recording-IN\Ultimate\Protocol #58\`, the TO's `timestamps\<slug>\` folder in `Recording-OUT\Ultimate\Protocol #58\dock\`. The project's `Ultimate Dock\` is still the 2026-10-26 version: archive it and copy in the new one. Then build the Ultimate cut (no replays: cut from the dock log).
0. **#57 post-processing on the desktop (2026-10-29).** #57 had ~2x the usual turnout and **5 setups** (1 stream + 4 replay-only). Recording `Recording-IN\2026-10-26 19-37-55.mp4` (4.6 GB) is copied in. No backup copy needed this time: the source stays on the laptop until #57 is done. Upload: `python slippi_uploader.py "Protocol #57"`. The uploader now offers to upload drives that are already plugged in, refuses to reuse a folder name already uploaded that night (two setups' sticks can share a label, e.g. "USB DRIVE"), and prints a summary. Uploaded 2026-10-29 (stick BICHON has failing flash, retire it; see VODCUTTER notes): labels SETUPTWO = "Big Tv", BICHON = "Hyraks", BJH = "BJH" (plus SETUPONE, GRACE). All 21 sets matched and rendered (per-setup Full VODs + upload kit); see VODCUTTER notes "Protocol #57". Next: uploads, entrant review, then Lucky Stats export (context.json format: github.com/0xburn/auto-vlerk-game-data-mapper). Then vod_config for #57: `"season": "Halloween"`, `clock_offset_s` per setup (5 now), `stream_setup` "Main Setup". Lucky Stats: user has a plan for uploads once sets are split; context.json format = https://github.com/0xburn/auto-vlerk-game-data-mapper (sample set folder in the project root).
1. **PROTOCOL #57 (Mon 2026-10-26), Halloween is ready.** Day-of checklist:
   - The dock's start.gg pointer is still on the test bracket `superstreambros`: in ⚙ click **Use latest (ProtocolSOVA)** and pick our stream.
   - Theme is already **Halloween** (orange badge in the dock header); OBS collection "Protocol Dock" shows the Halloween overlay + spooky round names. Twitch title updated by the user 2026-10-25.
   - Banner: the user's `Seasonal\Halloween\banner_layers\HalloweenBanner.pdn` needs a PNG export from paint.net for start.gg (user does this).
   - After #57: switch the dock theme back to **Default**; in `Recording-OUT\Protocol #57\vod_config.json` set `"season": "Halloween"` so replay-rendered sets match the stream.
2. **Next session: m-overlay in the VODs** (see VODCUTTER_PROJECT_NOTES "Next steps").
3. Stream Dock: the event log for the VOD cutter.
4. Later themes (Christmas, anniversary, #75 special): new folder in `Seasonal\` (README "Adding a seasonal theme"); `make_halloween_art.py` is the template for scripted art.
5. ~~Stage 4 (Lucky Stats export)~~ Done 2026-11-04: `tools/luckystats_export.py <plan.json> <replays> <out> [--repaired dir]`. Format = auto-vlerk-game-data-mapper's buildContext (bestOf, startMs, scores before each game, finalScore, players, startgg tournament/event/set ids, mapping files+sha256). That mapper itself can't map our sets (start.gg has no per-game character reports), so games come from the VOD cutter's reviewed plan; startMs = corrected laptop time (Wii clocks are wrong). #57: 21 sets (P was a DQ). #58: 22 sets. Upload: one zip per set (`LuckyStats<t>zips`) on the Lucky Stats upload page; #58 GF accepted and live 2026-11-04 (luckystats.gg/set/11522721), format confirmed. #58 event page: luckystats.gg/event/310766. **Corrections (2026-11-10, #59): re-uploading the full set of zips replaces wrong sets** (same start.gg set id = same Lucky Stats set), so fix the export and re-upload; no need to ask Lucky Stats to delete. But the set **score** on Lucky Stats comes from start.gg and isn't refreshed by a re-upload: #59 C still showed the original 4-0 and I the original 3-0 after both were fixed on start.gg (games shown were the zip's correct 3 and 4). Waiting to see if it refreshes on its own; otherwise ask the Lucky Stats admins to re-sync.

## Set analysis (requested 2026-11-10, start after #59 is uploaded + on Lucky Stats)
- Goal: write a per-set analysis as each set renders (the replays are already parsed then), in Lucky Stats' breakdown style (openings, neutral wins, punish/defense, conversions, kills per opening, etc.) **plus what Lucky Stats lacks: a mindset read across the set** (e.g. a player speeding up / autopiloting vs slowing down and playing tactically; what adjustments were made between games or stocks, and what adjustment might have changed the result, if any).
- Reference how top players approach each matchup.
- Data available per game from the .slp: frame-by-frame inputs + action states, so pace/mindset can be measured, not guessed: actions per minute and its trend by stock/game, time to re-engage after losing or taking a stock, option repetition (ledge, tech, out-of-shield, recovery) and whether it changes after being punished, approach/neutral choices per stage, stage picks between games.
- 2026-11-10: first version `tools/slp_analyze.py <my port> <games...>` (JSON): Slippi-style conversions (neutral win / counter / trade, damage per opening, openings per kill, kill moves/percents), what the victim was doing when opened, grabs tried/landed, tech situations + follow-ups, crouch -> dash, what each player did right after hitstun and whether they were re-hit, aerial hit/shield/whiff + punished, responses to the opponent's crouch and shield, inputs/min while actionable, per-stock pace, game timeline. Used for FRjhracing's #59 sets A (vs Hyraks Fox) and P (vs Rhan Samus). Deaths below the stage are found from the stock-loss position. All heuristics: treat counts as approximate.
- 2026-11-10: success/fail clip pairs (6 situations, 12 clips, 8-10.5 s each, cut from the set videos) + local review page at `I:\Protocol VOD\Melee Analysis\Protocol #59 - FRjhracing\` (`Protocol 59 set review.html`, `clips\`, `clips\clips.json` = clip times). The page uses relative paths, so it only works opened from that folder (not as a claude.ai Artifact). Situation frames come from the analyzer's `events` output; clip times verified against the in-game timer (within ~1 s). Set-video time: rebuilt game 1 = frame time from -123; later stream games = rebuilt length + video_t - take_over + frame/60; replay sets = sum of earlier gN_overlay.mp4 lengths + (frame+123)/60.
- 2026-11-11: **Lucky Stats links in the Melee video descriptions** (user). Lucky Stats numbers sets itself (e.g. #59 C = luckystats.gg/set/11657543), so the links are collected after the zips are uploaded (the user pastes them; fetching luckystats.gg from here hits a 429 rate limit). Put them in vod_config `"luckystats": {"<set letter>": "<Lucky Stats set id or URL>", "_event": "<event URL>"}`, run `vod_cutter.py kit`, then `youtube_upload.py tags <folder>`, which now also syncs descriptions of already-uploaded videos. Sets get a "Stats:" line under "Bracket:"; Full VODs get the event link.
- Open: where the write-up goes (YouTube description, a doc per set, Discord), tone for local players, and which top players' approaches to reference per matchup.

## Channel art (SoVA Protocol YouTube, 2026-11-11)
- `ChannelArt\make_sova_avatar.py` -> `sova_avatar.png` (800x800 channel picture) and `make_sova_banner.py` -> `sova_banner.png` (2560x1440; everything in the 1546x423 safe area). Built from the project's own art only (Protocol emblem from the overlays, Ultimate scoreboard plates/glow, Melee overlay orange, Typo Round font); no Nintendo cover art or logo lettering. Needs Pillow.
- 2026-11-11: **replay retention** (user): local replays are deleted once the user confirms a tournament's Lucky Stats upload is verified (keep match data + READMEs). Drive `Protocol #N` folders are the fail-safe; the user deletes them by hand, and gets a reminder when they're 2 weeks old. #51-#56 were never on Lucky Stats (exports started at #57).
