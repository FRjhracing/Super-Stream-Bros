# Render PC handoff strategy

Written 2026-11-17 on the render PC (RENDER-PC, project `<render PC project folder>`).
This describes how the render PC **currently** uses the data that arrives from the stream laptop, the Melee
Stream Dock, the Ultimate Dock, Slippi and start.gg. It is meant to help tune the docks and the handoff
so the VOD tools get what they need. The dock data formats themselves are in `RENDER_PC_HANDOFF.md`
(project folder) and are not repeated here.

---

## 1. What arrives, where it goes, what reads it

| Input | Comes from | Lands on the SSD at | Read by | Used for |
|---|---|---|---|---|
| Melee stream recording (`YYYY-MM-DD HH-MM-SS.mp4`) | OBS on the laptop, recorded straight to the SSD | `MeleeRecordings\Protocol-N\` | `vod_cutter.py` | stream sets are cut from it; **file name = recording start** (the time base for every stream cut) |
| Melee dock `setups.jsonl` | Stream Dock `timestamps\protocol-N\` | copied to `MeleeRecordings\Protocol-N\`, then to `Protocol VOD\Melee\Protocol #N\dock\` | `vod_cutter.py` (`"dock_log"`) | which setup each set was on + a rough time window (section 2) |
| Melee dock `setups.csv`, `Setup times.txt` | same | same | **nobody** (people only) | - |
| Melee `player_prefs.json`, `dock_state.json`, `dock_config.json`, `setup_state.json` | Stream Dock | `MeleeRecordings\Protocol-N\` (#59) | **nobody** | - |
| `.slp` replays, one folder per setup | flash drives via `slippi_uploader.py` | `Protocol VOD\Melee\Protocol #N\replays\<setup>\` (+ Drive `gdrive:Protocol #N`) | `vod_cutter.py` via `slippi_scan.py` | **the main source**: games, times, characters, colours, winners, stage; off-stream sets are rendered from them |
| Ultimate recordings (1 or 2 per night) | the Ultimate TO's OBS, recorded to the SSD | `UltimateRecordings\Protocol #N\` | `ultimate_cutter.py` | all Ultimate videos |
| Ultimate dock `log.jsonl` | Ultimate Dock `timestamps\protocol-N\` | copied to `Protocol VOD\Ultimate\Protocol #N\dock\` | `ultimate_cutter.py` (`"dock"`) | **the only source of cut times** (no replays for Ultimate) |
| Ultimate dock `characters.json` (per set) | same | same | `ultimate_cutter.py` | characters in titles and the overlay |
| `player_characters.json` (per player, all weeks) | Ultimate Dock | `UltimateRecordings\player_characters.json` | `ultimate_cutter.py` | thumbnail character when a set has none |
| Ultimate `setups.jsonl`, `*.csv`, `Recording N chapters.txt`, `Setup times.txt` | Ultimate Dock | with the recordings | **nobody** (people only) | - |
| start.gg (API, `STARTGG_TOKEN`) | live | cached in `work\startgg.json` | both cutters, kits | entrant names, rounds, **final scores**, set ids/links, stream assignment, `startedAt`/`completedAt` |

---

## 2. Melee: how the data is combined (`vod_cutter.py plan`)

The replays decide what was played. The dock and start.gg narrow down where and when.

1. **Replays are scanned** (`slippi_scan.py`): per game the Wii start time, length, ports, characters,
   costumes, winner, end method, CPU/human. Games under the minimum length, no-contests, doubles and
   anything with a CPU are not counted.
2. **Wii clock to laptop clock**: each setup's `clock_offset_s` in `vod_config.json` (seconds, or a
   `{"wii": ..., "laptop": ...}` anchor for Wiis with the wrong date). This is set **by hand every week**:
   - Main Setup's Wii clock is reset by hand each week (dead battery), so it's recalibrated from the
     in-game timer on stream (#59: -41 s).
   - Other Wiis drift or sit on the wrong date/DST (BZimm +3657 s on #58 and #59; Big Tv set to 2025).
   - The dock windows are what show whether an offset is right (a set whose characters look wrong =
     wrong clock, found on #59 K).
3. **Same-player runs**: consecutive games on one setup with the same players. Handwarmers (up to 2
   games with identical characters right before a set) are trimmed from the front.
4. **Per start.gg set** (completed, not DQ): candidates = the last N games (N = start.gg score total) of a
   run that ends before the report and whose winners fit the score.
   - **Dock log used here:** if the set has dock segments, candidates are limited to the setups the dock
     put it on, and the search window starts at the earliest dock "on" time (or start.gg `startedAt`,
     whichever is earlier). If nothing fits on the dock's setup, another setup is allowed and flagged.
   - Dock setup names map to replay folder names by a loose match (case, "setup", trailing s ignored);
     `"dock_setups"` in the config overrides it. Unmapped names are listed at the top of `review.md`.
5. **Picking** between candidates: stream-assigned sets (start.gg stream = ours) go to Main Setup first;
   then the clearest set is taken one at a time, scoring by each player's characters/colours from sets
   already matched.
6. **Which sets are "on stream"** = sets whose games are on the Main Setup replay folder. **Not** taken
   from the dock's Main Setup segments directly.
7. **Video time** of a stream game = replay time (laptop clock) - recording start from the file name.
   The dock's `t` is **not** used for cut points: cuts come from replay times + 10 s padding.
8. `review.md` gets dock notes per set: zero-length entries, re-reports, moves between setups,
   overlapping segments, sets missing from the dock.

### What Melee does *not* take from the dock
- Cut points (replays are frame-accurate, the dock is click-accurate).
- Characters/colours (replays; `player_prefs.json` is ignored).
- Scores (start.gg's final score; a `"score"` override when start.gg is wrong, e.g. #59 C).
- Overlay history: the VOD overlay is re-rendered from start.gg + replay winners (`overlay_stream`).

---

## 3. Ultimate: how the data is combined (`ultimate_cutter.py plan`)

No replays, so the dock log is the timeline.

1. `log.jsonl` sorted by `t`; `on_stream` paired with the next `set_end` on the same recording.
2. **Video time = `t` - latest `rec_start` for that recording**, else the OBS file name time.
3. A set logged more than once keeps its longest window. 15 s padding each side; padding overlaps meet
   in the middle.
4. start.gg gives names, round and final score (it wins over the dock's `result` text; a disagreement is
   noted).
5. Characters: config override, else `characters.json` by set id, else by set letter.
6. `scan` (part of `render`) then refines each cut from the video: VS screens give game starts (cut =
   20 s before game 1's VS), results screens give winners and the end (8 s after the last one).
   Handwarmers are dropped from the front when the VS count is over start.gg's game count.
7. Sets the dock missed or got badly wrong are cut by hand in the config (`"start"`, `"end"`, `"rec"`)
   from contact sheets, and listed in `questions_for_TO.txt`.

What went wrong in practice: on #58 top 8 the TO was playing / catching up on reports, so on-clicks came
late (up to 11 min), one set was never logged, one was logged as 25 s. On #59 three sets played on Main 1
were never put on the recording, and one end was the report time. All fixed by watching the recording.

---

## 4. The manual steps each week (where time goes)

| Step | Melee | Ultimate |
|---|---|---|
| Copy dock files into the tournament folder's `dock\` | by hand | by hand |
| Point config at the recording | by hand (file name changes weekly) | by hand |
| Wii clock offsets | **by hand, every setup, every week** (biggest risk of a wrong match) | n/a |
| Dock setup name -> replay folder | automatic, override if needed | n/a |
| Fix sets the dock missed | rarely needed (replays cover it) | **often** (watch the recording) |
| Score / game fixes | config overrides | config overrides |

---

## 5. Where the handoff could improve (ideas, not decided)

Melee
- **Clock offsets are the weak point.** The dock already gives a window per set per setup. The cutter
  could estimate each setup's Wii offset itself (the offset that makes the most replay runs fall inside
  their dock windows) and only ask for confirmation. Better dock data = tighter windows: an on-click when
  players actually start, and the report click soon after the set ends.
- A one-click "game started" or "set started" in the dock isn't needed for Melee: replays already have it.
- Main Setup offset: the dock could log one "GO" moment (or the TO notes the in-game timer at a known
  time) to replace the weekly timer reading.
- Use the dock's Main Setup segments as a cross-check for "on stream" (now inferred from the replay folder).
- `player_prefs.json` / overlay state are not needed on the render PC; don't bother copying them.

Ultimate
- **`log.jsonl` is required.** Without it the plan is empty: the reader silently returns nothing.
  **#60 (2026-11-16) currently has only the `.txt` exports and `characters.json` in
  `UltimateRecordings\Protocol #60\`, no `log.jsonl` / `setups.jsonl`.** Either get the TO's
  `timestamps\protocol-60\` folder, or #60 has to be cut from the chapter text / by watching.
  (Fix on the render PC side: stop with a clear message when `log.jsonl` is missing.)
- The VS-screen scan already finds game starts, so the dock's job is mainly "which set, which recording,
  roughly when". Missed sets hurt more than late clicks.
- `Setup times.txt` for #60 shows most sets on Main 1 ended "set over (by hand)": fine for cutting, but
  then the score comes only from start.gg.
- Pressing "Rec started" matters: it removes the file name fallback (#60 Recording 1 has it, 19:15:37).

Both
- One fixed drop spot per tournament on the SSD for the dock's `timestamps\protocol-N\` (e.g. next to
  the recording) would let the cutters find the dock files without the copy step: the config would only
  need the tournament number.
