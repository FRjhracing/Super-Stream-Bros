# Render PC handoff: dock data for the VOD cutter (written 2026-11-03 on the stream laptop, updated 2026-11-11)

For the Claude session on the render PC (desktop, 7900 XTX). Rendering and uploading moved there; the laptop
only streams, records and runs bracket. Since that PC's notes were last synced, both OBS docks gained a
**"Put on setup" timestamp log**, and the Ultimate Dock gained **per-set characters** and a **player → character**
file. This file describes what the user will copy over, the exact data formats, and how the two docks differ.

**Status 2026-11-11:** the VOD cutter lives on the render PC only and already reads the setup log. The laptop's old
copy was archived (`_archive\vod_cutter_2026-11-11_moved_to_render_pc\`); it is far behind the render PC's version, so
don't use it as a reference. This file is the contract for what the laptop hands over. Read "What changed
2026-11-11" first: it lists the log changes the cutter has to expect.

---

## 0. What changed 2026-11-11 (Melee dock)

1. **Folders renamed.** `StreamDock\` is now `Super Stream Bros Melee\`, `Ultimate Dock\` is now
   `Super Stream Bros Ultimate\` (project folder: `SuperStreamBros`, was `SlippiUploader`). Logs are still in
   `<dock folder>\timestamps\<slug>\`. Older copies on the render PC keep their old folder names; the contents are the same.
2. **One segment per set, even when a result is reset and reported again.** Before, a re-report wrote a second
   `on_setup` (backdated, note "setup picked at report") plus a second `set_end`: two starts for one set (see Q on
   #58). Now the dock appends corrections that point at the original segment through `seg`:
   ```json
   {"id": "…209", "t": 1794440528.209, "setup": 1, "setupName": "Main Setup", "event": "on_setup", "setId": "555", "identifier": "B", …}
   {"id": "…224", "t": 1794440528.224, "setup": 1, "setupName": "Main Setup", "event": "set_end", "seg": "…209", "reason": "reported in dock", "result": "T6 3-1 T1"}
   {"id": "…301", "t": 1794440528.224, "setup": 1, "setupName": "Main Setup", "event": "set_end", "seg": "…209", "reason": "re-reported in dock", "result": "T6 2-1 T1", "note": "result corrected at 18:42:08; end time kept from the first report"}
   {"id": "…355", "t": 1794440590.244, "setup": 2, "setupName": "Setup 2", "event": "setup_fix", "seg": "…209", "note": "setup corrected at re-report (was Main Setup)"}
   {"id": "…356", "t": 1794440528.224, "setup": 2, "setupName": "Setup 2", "event": "set_end", "seg": "…209", "reason": "re-reported in dock", "result": "T1 2-0 T6", "note": "…"}
   ```
   How to resolve a segment (reference: `Dock.segments()` in `Super Stream Bros Melee\dock_server.py`):
   - **start** = the `on_setup` line (`id` = the segment id). Never changes.
   - **end / result** = the **last** `set_end` with that `seg`, in file order. A corrected end repeats the first end's
     `t` on purpose (the match ended then), so **don't sort ends by `t` alone**: ties must keep file order
     (`id` is a nanosecond counter and always increases, so sorting by `id` also works).
   - **setup** = the last `setup_fix` with that `seg` if there is one, else the `on_setup`'s. Use it for the replay
     folder and for "was it on stream" (Main Setup). A `setup_fix` has no time meaning; ignore its `t`.
   - Unknown `event` values: skip them (more correction types may be added).
   - `setups.csv` lists every raw line including the corrections; `Setup times.txt` shows the resolved view and tags
     a moved segment `[setup corrected, was <name>]`.
3. **Bracket restarted on start.gg = sets start fresh.** (It has happened at Protocol: a late arrival, seeding
   redone, round 1 restarted.) A restart gives every set a new id. What the log shows:
   - Sets that were on a setup at the restart get a `set_end` with **`reason: "bracket restarted"`** (no `result`;
     `t` = when the dock noticed, up to about a minute after the restart). **Discard those segments**: the match
     was voided. When the set is played again it gets a new `on_setup` with a new `seg`.
   - Sets finished before the restart keep their complete segment, but its `setId` no longer exists in the final
     bracket. Default rule: **a segment whose numeric `setId` isn't in the final bracket is from before a restart;
     discard it.** Exception worth flagging for review: if the same two players have a set in the final bracket
     with only a zero-length "setup picked at report" segment (the TO re-entered the old result instead of
     replaying), the discarded segment holds the real times and setup of that match.
   - Nothing is deleted from the log, and the dock writes no separate "restart" marker line.
4. **Still two segments (by design):** a set that was reset and then *put on a setup again* (really replayed), a set
   moved between setups mid-set (`moved to`), and anything logged before 2026-11-11. The #58 rules in section 3 still
   apply to old logs.
5. **Bracket start.** On an offline event the first "Put on setup" of the night starts the whole bracket on start.gg;
   its API then returns no sets for about a minute and every set gets a new numeric id. Sets put on a setup in that
   minute are logged immediately with their `preview_…` id and the correct time (the start.gg "start" call is queued
   and sent later, which doesn't touch the log). So several `on_setup` lines with preview ids at the start of the
   night are normal; match them as before (identifier + both players, the `set_end` has the numeric id).
6. **Seeds, page names, touch layout:** dock display only. No effect on any file handed over.
7. The **Ultimate dock** got the same changes on 2026-11-11 (items 2-5 apply to its `setups.jsonl` from the first night the TO runs the new zip; nights before that are in the old format). Ultimate specifics: a restart also ends the recording entry in `log.jsonl` with `set_end` / `reason: "bracket restarted"` (discard that `on_stream` segment). A re-reported result is corrected in `setups.jsonl` only; `log.jsonl` keeps the first `set_end` result, so **take results from `setups.jsonl` (last `set_end` per `seg`) or from start.gg**. A `setup_fix` onto a recorded setup carries `stream` but has no `on_stream` line in `log.jsonl`: trust `log.jsonl` for what was recorded.

---

## 1. What gets copied to the render PC (by hand)

| From (stream laptop / Ultimate TO's PC) | What it is |
|---|---|
| `%USERPROFILE%\Videos\Main OBS Out\2026-11-02 19-37-13.mp4` (4.2 GB) | Melee stream recording, PROTOCOL #58. Put in `Recording-IN\` + `Recording-BACKUP\`. |
| `%USERPROFILE%\Videos\Main OBS Out\2026-10-26 19-37-55.mp4` (4.6 GB) | Melee stream recording, PROTOCOL #57 (Halloween theme). |
| `Super Stream Bros Melee\timestamps\protocol-58\` | Melee dock setup log for #58 (first real use). |
| `Super Stream Bros Ultimate\characters.json` | start.gg Ultimate cast list (static). |
| `Super Stream Bros Ultimate\player_characters.json` | Ultimate player → characters per set (seeded from YouTube, grows from the dock). |
| Ultimate TO's `timestamps\protocol-57\` and/or `protocol-58\` + their 2 recordings per night (external SSD) | Ultimate recording logs. See section 4 for which format each night will be in. |

Suggested place on the render PC: keep the same relative paths (`Super Stream Bros Melee\timestamps\<slug>\`,
`Super Stream Bros Ultimate\timestamps\<slug>\`) so code can find them by tournament slug.

Replays still come from Drive as before (`rclone copy "gdrive:Protocol #58" "Local Replays\Protocol #58"`).

**Since 2026-11-17 (supersedes the table above for new weeks):** the laptop's handoff is the "Stream PC handoff"
skill (`.claude\skills\stream-pc-handoff\`). It copies only the Melee recording + `setups.jsonl`, `setups.csv`,
`Setup times.txt` to the external SSD (`Project Storage`) at `MeleeRecordings\Protocol-N\`. **Replays are uploaded
from the flash drives on the render PC**, not from the laptop, so they're never part of the laptop's copy. Ultimate
files come from the Ultimate TO directly (`UltimateRecordings\Protocol #N\`). Laptop-side summary:
`<SSD>\Stream laptop handoff strategy.md`.

---

## 2. Common ground (both docks)

- **One folder per tournament**: `timestamps\<slug>\`, slug = start.gg tournament slug (`protocol-58`).
- **`*.jsonl` is the source of truth.** The `.csv` and `.txt` files are regenerated from it on every write.
  Read the jsonl, never parse the txt.
- **Append-only, one JSON object per line**, UTF-8. Lines may be out of time order (backdated starts):
  sort by `t` (stable sort, so same-second events keep file order). Skip lines that don't parse.
- **`t`** = Unix epoch seconds (float, 3 decimals) from the machine running the dock.
  `id` = `time.time_ns()` of when the line was *written* (string). For backdated events `id` is later than `t`.
- **Clocks**: the dock runs on the same PC that records, so dock `t` and the OBS file name
  (`YYYY-MM-DD HH-MM-SS` = local recording start) share one clock. **No calibration needed between dock and
  recording.** Melee replays (Wii clocks) still need the per-setup offset vs. this clock.
  Convert `t` to local time with the render PC's timezone (both PCs are in the same zone).
- **Set identity**: `setId` (start.gg id, string), `identifier` (set letter, "A".."AJ"), `round`
  (start.gg `fullRoundText`; Melee: may be a themed name on themed weeks), `p1` / `p2` (entrant names as
  shown on start.gg, incl. sponsor prefix e.g. "OAC | Hyraks").
  - **`setId` can change mid-log**: before the bracket starts, start.gg ids are `preview_<phaseGroup>_<round>_<n>`
    and become numeric once it starts. Example in #58: set B starts as `preview_3515422_1_3`, ends as `109670971`.
    Match sets by **id, else (identifier + both players)**. Use the latest numeric id.
- **Segments**: a set on a setup = one `on_setup` event + one `set_end` event. **Pair them by `seg`**:
  the `set_end` carries `seg` = the `id` of its `on_setup`. (Older lines without `seg`: the start's own `id`.)
  A start with no end = still playing when the log was copied (or the dock was closed mid-set).
- **Corrections (Melee dock, since 2026-11-11)**: a set whose result is reset and reported again keeps its ONE
  segment (same start). The log is append-only, so the correction is extra lines with the same `seg`:
  - another `set_end` (`reason: "re-reported in dock"`): **the last `set_end` of a `seg` is the result that counts**.
    Its `t` repeats the first end's `t` (the match ended then; only the result was fixed).
  - `setup_fix`: the segment was really on the `setup` / `setupName` of this line (the TO picked another setup
    at the re-report). Apply the last `setup_fix` of a `seg` to its start.
  `Setup times.txt` shows the resolved view (`Dock.segments()` in the dock server is the reference resolver).
  Logs from before that date can hold two segments for a re-reported set (the second one has the
  "setup picked at report" note and nearly the same start): keep the first start, the last result.
- **End reasons** (`set_end.reason`):
  `reported in dock` (has `result`), `reported` (seen on start.gg by the 20 s poll, `t` = start.gg `completedAt`,
  has `result`), `next set on <setup>`, `moved to <setup>`, `cleared by hand` / `taken off by hand`,
  `setup removed in settings`, `bracket restarted` (Melee, discard the segment; see section 0), `re-reported in dock`
  (Melee, correction), Ultimate also `set over (by hand)`.
- **`result`** text: `"PhaT 3-0 bjh500"` (winner first) or `"DQ: <tag>"`.
- **"setup picked at report"** (`note` on an `on_setup`): the set was never put on a setup; the TO chose the setup
  in the report dialog. Start is backdated to start.gg `startedAt` when known
  (`note: "setup picked at report; start = start.gg start time"`, `startedAt` field present), otherwise
  `start unknown` and start = report time (**zero-length segment: setup is known, times aren't**).
- **Only sets touched in the dock are logged.** A set reported straight on start.gg and never put on a setup
  has no entry. Times are when the TO clicked: expect a few seconds to minutes of slack either side.

### Event record: `setups.jsonl` (both docks)
```json
{"id": "1793666001134242500", "t": 1793666001.134, "setup": 3, "setupName": "BJH", "event": "on_setup",
 "setId": "preview_3515422_1_3", "identifier": "B", "round": "Winners Round 1", "p1": "PhaT", "p2": "bjh500"}
{"id": "1793666522846782100", "t": 1793666522.847, "setup": 3, "setupName": "BJH", "event": "set_end",
 "setId": "109670971", "identifier": "B", "round": "Winners Round 1", "p1": "PhaT", "p2": "bjh500",
 "seg": "1793666001134242500", "reason": "reported in dock", "result": "PhaT 3-0 bjh500"}
```
| field | notes |
|---|---|
| `setup` | 1-based setup number (position in the dock's list at the time) |
| `setupName` | name at the time. Prefer the name; numbers shift if setups are renamed/reordered in ⚙ |
| `event` | `on_setup`, `set_end`, or `setup_fix` (correction, Melee dock; see section 0). Skip values you don't know |
| `startedAt` | optional, start.gg `startedAt` (epoch) |
| `seg` | on `set_end` and `setup_fix`: id of the `on_setup` they belong to. A seg can have several `set_end` lines (last one counts) |
| `note`, `reason`, `result` | optional, see above |
| `stream` | **Ultimate only**: `"1"`/`"2"` when that setup is captured by Recording 1/2 |

---

## 3. Melee Stream Dock (`Super Stream Bros Melee\`, laptop, port 8765)

- Files in `timestamps\<slug>\`: **`setups.jsonl`**, `setups.csv` (adds clock time + start.gg start, UTF-8 BOM),
  `Setup times.txt` (human summary). That's all: **no `log.jsonl`, no recording-start event, no characters.**
- **Setup 1 is always "Main Setup"** (fixed name = the SETUPONE replay folder name on Drive). It is the stream
  setup (`streamSetup: 0` in `dock_config.json`). So: `on_setup` segments with `setupName == "Main Setup"` =
  what's on the stream recording. Other setups = off-stream (render from replays).
- **Setup names = replay drive folder names, mostly.** #58's list: `Main Setup`, `Bzimm's Setup`, `BJH`, `Biggie`.
  The Drive folders come from drive volume labels (`slippi_uploader_config.json`), so names may not match exactly
  (e.g. dock "Bzimm's Setup" vs Drive "BZimm's"). Map dock setup → replay folder in `vod_config.json`, don't assume.
- **Video time** for the stream: `t` − recording start from the file name. #58 recording starts 19:37:13; the first
  Main Setup set (C) went on at 19:36:25, before the recording. Clamp to 0.
- **"Move set to stream"** (player picker): a set already on another setup moves to Main Setup → its old segment ends
  with `moved to Main Setup` and a new Main Setup segment starts. Mid-set: games before the move are on the other
  setup's replays, the rest on stream.
- **Characters**: the Melee dock doesn't log them; **replays are the source** (character + costume per game).
  `Super Stream Bros Melee\player_prefs.json` = last character/color used on the overlay per tag
  (`{"BZimm": {"character": "Yoshi", "color": "red"}}`, Stream Updater color names). Only a hint/fallback;
  not copied over unless wanted.
- The overlay state (`dock_state.json`) is current-only, no history. Not useful for rendering.

### #58 (2026-11-02) log: 50 events, 4 setups. Quirks the matcher must handle
- **J (Winners Semi, moose vs Bichon Frise)** has two overlapping segments: Main Setup 20:22:58–20:26:32 (ended by
  "next set on Main Setup", likely put there by mistake) and Bzimm's Setup 20:22:58–20:40:48 (setup picked at report,
  backdated). The result-bearing segment (Bzimm's) is the real one. Rule: prefer the segment whose end has a `result`;
  a segment ended by `next set on`/`moved to` within a few minutes and no replays matching = discard.
- **Q (Losers R1, FRjhracing vs girllover10000)** on BJH: reported `FRjhracing 3-0` at 20:15:02, then a zero-length
  segment at 20:16:32 with `girllover10000 3-0 FRjhracing` (set was reset and re-reported with the right winner).
  Rule: the **last** result for a set wins; times come from the real (non-zero-length) segment.
- **T (Losers QF, PhaT vs Biggie)**: Bzimm's Setup 20:41:55–20:43:43 then `moved to Main Setup`, Main Setup
  20:43:43–20:58:24. Some games may be on Bzimm's replays.
- **B**: preview id at start, numeric at end (see section 2).

---

## 4. Ultimate Dock (`Super Stream Bros Ultimate\`, the Ultimate TO's PC, port 8766)

Self-contained copy (no shared code with `Super Stream Bros Melee\`). **No replays exist for Ultimate**, so the log is the only
way to cut the videos. Two OBS instances record: **Recording 1** (main OBS, hosts the dock) and **Recording 2**
(portable OBS). UI says "Recording"; internally and in the logs it is still `stream` (`"1"`/`"2"`).

Files in `timestamps\<slug>\`:
| file | what |
|---|---|
| **`log.jsonl`** | recording log (source of truth for cutting) |
| **`setups.jsonl`** | setup log, same format as Melee plus `stream` |
| **`characters.json`** | characters per set this tournament |
| `timestamps.csv`, `setups.csv` | exports (UTF-8 BOM) |
| `Recording 1 chapters.txt`, `Recording 2 chapters.txt` | per recording: video time, set, characters, clock time. Older builds: `Stream N chapters.txt` |
| `Setup times.txt` | per setup, recorded or not, start–end, minutes, characters |

### `log.jsonl` (recordings)
```json
{"id": "...", "t": 1793057000.123, "stream": "1", "event": "rec_start"}
{"id": "...", "t": 1793057627.456, "stream": "1", "event": "on_stream", "setId": "109...", "identifier": "C",
 "round": "Winners Round 1", "p1": "OAC | ApplSaucFactory", "p2": "..."}
{"id": "...", "t": 1793058400.789, "stream": "1", "event": "set_end", "setId": "109...", "identifier": "C",
 "round": "Winners Round 1", "p1": "...", "p2": "...", "reason": "reported", "result": "A 2-1 B"}
{"id": "...", "t": 1793058000.000, "stream": "2", "event": "mark", "note": "audio cut out", "setId": "..."}
```
- `event`: `rec_start` (TO pressed "● Rec started" when that OBS began recording), `on_stream`, `set_end`, `mark`.
- **Video time = `t` − the most recent `rec_start` for that `stream`** (a new `rec_start` = the recording was
  restarted = new file). If no `rec_start`: use the OBS file name time (TO was told to keep default names).
  Expect `rec_start` to be a few seconds late (button pressed after Start Recording).
- **`log.jsonl` has no `seg`**: pair `on_stream` with the next `set_end` on the same `stream`. A set can only be on one
  recording at a time. `set_end.reason` here: `reported` (dock or start.gg, has `result`), `ended by hand`
  ("■ Set over"), `taken off by hand`, `next set on recording N (X)`, `moved to recording N`,
  `moved to Setup 3 (not recorded)`.
- Rows can be deleted by the TO (✕), so there are no tombstones: what's in the file is what they kept.
- `mark` = TO's free marker (highlight or recording problem); worth listing in the review.
- `setups.jsonl` duplicates the recorded sets (same `t`, with `"stream": "1"`) and adds the unrecorded setups
  (data only: set lengths and locations, nothing to cut).

### `characters.json` (per tournament, by set id)
```json
{"109670969": {"identifier": "C", "round": "Winners Round 1", "p1": "A", "p2": "B",
               "chars1": ["Link", "Ryu"], "chars2": ["Terry"], "t": 1793057700}}
```
- `chars1` belongs to `p1` **of this record**. If a log event lists the players the other way round
  (`ev.p1 == rec.p2`), swap. Lookup: by `setId`, else by `identifier` (preview ids).
- 0–3 characters per player, in order played. Names are start.gg's exact names (from `Super Stream Bros Ultimate\characters.json`).
  In titles "Random Character" is shortened to "Random": `Swizzy (Terry, Random)`.
- Sets reported on start.gg and never given characters in the dock have no entry.

### `Super Stream Bros Ultimate\characters.json` (cast list, static)
`{"source": "start.gg videogame 1386", "characters": [{"id": 1530, "name": "Banjo-Kazooie"}, ...]}` (87 incl. "Random Character").

### `Super Stream Bros Ultimate\player_characters.json` (player → characters, all tournaments)
```json
{"note": "...", "updated": "2026-11-02 15:57",
 "players": {"1966341": {"tag": "ApplSaucFactory", "sets": [
     {"tournament": "protocol-57", "set": "C", "round": "Winners Round 1", "chars": ["Link", "Ryu"],
      "t": 1793057627, "source": "youtube:RgbH_hG_sNs"}]}}}
```
- Key = start.gg **player id** (same every week), fallback `tag:<lowercased alnum tag>` when no id was known.
- `set` = set letter (or set id if no letter). `source` = `youtube:<videoId>` (seeded from the SOVA_Protocol channel
  titles by `ultimate_seed_chars.py`, #57 only so far: 21 videos, 20 sets, 18 players) or `dock` (entered at report).
- One entry per (tournament, set) per player; re-entering replaces it.
- **Merge, don't overwrite**: once the TO's copy has `dock` entries, combine theirs with ours (union by player id,
  replace by (tournament, set)).

### Which format each Ultimate night is in
- **#57 (2026-10-26)**: first dock build. Only `log.jsonl` + `timestamps.csv` + `Stream 1/2 chapters.txt`.
  No setups, no characters (characters for #57 are in `player_characters.json` from the YouTube titles).
  The TO already hand-edited and uploaded #57 to YouTube, so #57 is test data for the cutter.
- **#58 (2026-11-02)**: the TO's copy was patched mid-bracket (query page size); it should have setups + characters,
  but check which files are actually in their folder before relying on them.

### Ultimate video titles (TO's existing format on https://www.youtube.com/@SOVA_Protocol)
`Protocol #57 <Round> <A> (<chars>) Vs. <B> (<chars>)`

---

## 5. Melee vs Ultimate dock: differences at a glance

| | Melee Stream Dock | Ultimate Dock |
|---|---|---|
| Runs on | stream laptop, port 8765 | Ultimate TO's PC, port 8766 |
| start.gg game | Melee only (videogame 1) | Ultimate only (1386), singles first |
| Overlay | yes (writes `Super Stream Bros Melee\output\`) | none (recording only) |
| Recordings | 1 (OBS stream recording) | 2 (Recording 1 main OBS, Recording 2 portable OBS) |
| Recording log | none; stream = Main Setup segments, start from the file name | `log.jsonl` with `rec_start`, `on_stream`, `set_end`, `mark` |
| Setup log | `setups.jsonl` | `setups.jsonl` + `stream` field on recorded setups |
| Setup names | Setup 1 fixed "Main Setup" (stream); default Main Setup + Setup 2 | all renamable; default Setup 1–4; Rec 1 → Setup 1, Rec 2 → Setup 2 |
| Off-stream sets | rendered from `.slp` replays | not recorded, logged for data only |
| Characters | from replays (per game, with costume) | typed at report: `characters.json` per set, `player_characters.json` per player |
| Game-level data | replays: per-game start/end, stage, winner | none; only set start/end + final score |
| Clock offset to fix | Wii clock per setup (~30 s) | none |
| Cutting source | replays + dock log (log = which setup, which set, rough window) | dock log only |
| Current-state file | `setup_state.json` (not needed) | `dock_state.json` (not needed) |

---

## 6. To do on the render PC

1. **Melee: `setups.jsonl` in the cutter's matching (done on the render PC; update it for section 0: last `set_end` per `seg`, `setup_fix`, skip unknown events).** Use each segment as the set's time window and setup
   (after applying the per-setup Wii clock offset to the replays), then pick that setup's replays inside the window
   and keep the existing rules (drop short games, trim handwarmers from the front using start.gg's game count).
   Fall back to the current matcher for sets with no segment. Flag in `review.md`: sets with no segment, zero-length
   segments, overlapping segments (J on #58), moved sets (T), re-reported sets (Q).
   The window also answers "which sets were on stream" (Main Setup segments) without guessing.
2. Map dock setup names → replay folders in `vod_config.json` (e.g. `"Bzimm's Setup": "BZimm's"`).
3. **Ultimate cutter** (new, no replays): overlay is ready in `UltimateOverlay\` (copy the folder; README there:
   `build_overlay(png, state)` + `overlay_video(recording, [(start, end, png)], out, trim=, gain_db=)`).
   Per recording, cut each `on_stream`→`set_end` with padding, title with
   `characters.json` (`Protocol #N <Round> <A> (<chars>) Vs. <B> (<chars>)`), chapters per recording. Start with #57
   data (compare against the TO's YouTube uploads for cut accuracy).
4. Ultimate recordings are large (~80 GB / 3 h for two recordings on #57): check disk space first; keep the raw files
   read-only like Melee's `Recording-IN\`.
5. Make per-machine paths configurable (ISO, overlay PNG, font, ffmpeg); the render PC encoder is the 7900 XTX
   (`h264_amf`/`hevc_amf`).
