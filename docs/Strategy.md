# Strategy: how the data is combined

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

The guiding idea: **replays decide what was played; the dock and start.gg narrow down where and when.**
Replays are frame-accurate, carry characters/colours/winners and exist for every setup. The docks are
click-accurate (a person presses buttons) and start.gg is report-accurate. So the cuts come from replays, the
set identities from start.gg, and the dock tells which setup a set was on and roughly when.

The full handoff analysis from both PCs (as of 2026-11-17) is in `docs\reference\`:
`Render PC handoff strategy.md` (what the render PC uses) and `Stream laptop handoff strategy.md` (what the docks
produce, and answers to the render PC's ideas).

## 1. Inputs and who uses them

| Input | Comes from | Used by | For |
|---|---|---|---|
| Melee stream recording `YYYY-MM-DD HH-MM-SS.mp4` | OBS, recorded straight to the SSD | `vod_cutter.py` | stream sets; **the file name is the recording start**, the time base of every stream cut |
| Melee dock `setups.jsonl` | Melee Stream Dock `timestamps\protocol-N\` | `vod_cutter.py` (`dock_log`), `ssb_autopilot.py` | which setup each set was on + a time window per set; the autopilot also derives the Wii clock offsets from it |
| `setups.csv`, `Setup times.txt` | same | people only | - |
| `.slp` replays | flash drives via `slippi_uploader.py` | all Melee tools | the games: times, characters, colours, winners, stages; off-stream sets are rendered from them |
| Ultimate recordings | the Ultimate TO's OBS | `ultimate_cutter.py` | all Ultimate videos |
| Ultimate dock `log.jsonl` | Ultimate Dock | `ultimate_cutter.py` | **the only cut-time source for Ultimate** (no replays). Required. |
| Ultimate `characters.json`, `player_characters.json` | Ultimate Dock | `ultimate_cutter.py` | characters for titles, overlay, thumbnails |
| start.gg | live API | everything | entrants, rounds, final scores, set ids/links, stream assignment, start/report times |

Not needed on the render PC: the docks' `player_prefs.json`, `dock_state.json`, `dock_config.json`, `setup_state.json`.

## 2. Melee matching (`vod_cutter.py plan`)

1. **Scan** every replay. Not counted: games under 30 s, doubles, anything with a CPU, and no-contests, with one
   exception (step 4).
2. **Wii clock -> laptop clock** per setup: `clock_offset_s` (seconds the Wii is ahead, or a
   `{"wii": ..., "laptop": ...}` anchor). Wii clocks drift, lose DST changes and sometimes sit on the wrong year
   (seen: 2009, 2017, 2025). The stream setup's offset is calibrated so that a game's `video_t` = GO. This used to
   be set by hand every week; `ssb_autopilot.py` now estimates it (section 4).
3. **Same-player runs**: consecutive games on one setup with the same ports and players. At most one side may
   change character between games; both sides changing is allowed only within 90 s (a quick restart).
   **Handwarmers** (up to 2 games with identical characters right before the set) are trimmed from the front.
4. **Quit-out rule** (from #60): a no-contest where the quitter (L+R+A+Start) was on their **last stock** counts
   as the other player's game, but **only in the middle of a set**, never as its first or last game. Every counted
   quit-out is flagged in `review.md` and kept in `player_notes.json` (all tournaments) so repeat quitters show up.
5. **Candidates per start.gg set** (completed, not DQ): the last N games (N = start.gg's game total) of a run that
   ends before the report and whose winners fit the score. If the dock put the set on a setup, only that
   setup's runs count (another setup is allowed, but flagged), and the search window opens at the dock's start.
6. **Picking**: sets assigned to our stream on start.gg go to the stream setup first; then the clearest set is
   taken one at a time, scoring candidates by each player's characters/colours seen in sets already matched.
7. **Back-to-back sets between the same players** (from #60: Grand Final + reset played as one run of 6
   games): split by report order, the earlier-reported set takes the earlier games.
8. **Stream or not**: a set is "on stream" when its games are on the stream setup's replay folder.
9. **Video time** of a stream game = its laptop time - the recording start. Cuts = first game - 10 s to last game
   end + 10 s.
10. `review.md` explains every set (why it was picked, dock notes, characters per player, quit-outs) and lists
    every replay left out with the reason (friendly, vs CPU, quit after m:ss, handwarmer...).

### What Melee does not take from the dock
Cut points (replays are frame-accurate), characters (replays), scores (start.gg; a `"score"` override when
start.gg is wrong) and the overlay history (the VOD overlay is rebuilt from start.gg + replay winners).

## 3. Melee rendering

- **Stream sets** are cut from the recording; the overlay panel is rebuilt per game (names, pictures, round,
  stock icons of the characters actually played) and laid over the live one, with the webcam hole left clear.
- **Stream audio dropouts**: games listed in `replay_games` get their picture (game area) and sound from the
  replay render while the webcam stays live (#60: OBS lost audio for the first 24 minutes).
- **Recording started mid-game**: game 1 is rebuilt from its replay and the stream takes over after it.
- **Off-stream sets** are rendered from the replays (Dolphin frame + audio dump at up to ~2x real time) with a
  "REPLAY / off-stream setup" card in the webcam box.
- Audio: +10 dB with a limiter on the stream; replay audio matched to the stream's loudness.
- One **Full VOD per setup** (chapters per set) plus one video per set; YouTube chapters per game.
- Encoding: `h264_amf` 12 Mbps VBR, AAC 192k (YouTube's 1080p60 recommendation).

## 4. Clock offsets (the weak point, now automated)

Everything in Melee matching rests on the Wii clocks. A wrong offset doesn't fail loudly: it can make another
run of games "fit" (#59 K showed another set's Dr. Mario/Falco games; a player's characters looking wrong =
suspect the clock first).

`ssb_autopilot.py` estimates them from the dock windows (dock and recording share the laptop clock):
- For each replay folder: try every offset suggested by a game/window pair (so a wrong date or year is found),
  then sweep +-15 min in 5 s steps; keep the offset that puts the most games inside the windows (30 s slack).
  Confidence = share of dock windows that contain games, and whether another offset fits as well.
- No dock windows for a setup: start.gg's start/report times are used instead (weaker; flagged).
- The **stream setup** is then calibrated to a fraction of a second: one short stream game is rendered from its
  replay and its audio is located in the stream recording; two games must agree within 0.3 s.
- Tested on #60 against the hand calibration: BZimm 82 s (hand 80), Big Tv found one year off, BJH -48 s
  (hand 0; both fit every window), stream -2.5 s (hand -2.0); the plan came out identical, set for set and file
  for file.

## 5. Ultimate (`ultimate_cutter.py`) ★

No replays, so the dock log is the timeline: `on_stream` paired with the next `set_end` on the same recording,
video time = `t` - the recording's `rec_start` ("Rec started" button; else the OBS file name). 15 s padding.
A `scan` then refines each cut from the video (VS screens = game starts, results screens = winners and end;
handwarmers dropped when the VS count is over start.gg's game count). Sets the dock missed or got badly wrong are
cut by hand in the config from contact sheets and listed in `questions_for_TO.txt`; those videos stay private
until the TO confirms. In practice missed sets (TO busy in top 8) hurt more than late clicks.

## 6. Lessons learned, week by week

| Week | What happened | What changed |
|---|---|---|
| #55 | First game's replay missing (recording started during a pause) | cutter flags missing games instead of dropping the set |
| #56 | Round robin, 2 setups; 2 s false start and a 26 s restart before a set | short games are dropped before the handwarmer trim |
| #57 | 5 setups, Wii dates 2009/2017/2025, timing alone picked wrong sets | anchors for wrong dates; matcher rewritten (identity scoring); per-setup Full VODs; corrupted replay -> `slp_repair.py`; failing flash drive retired |
| #58 | First dock setup log; BZimm Wii still on daylight time (+3657 s) | dock windows narrow the candidates; overlay rebuilt on stream sets too |
| #59 | Stream setup's Wii clock reset by hand every week; wrong BZimm offset made K "fit" other games | weekly stream calibration; recording started mid-game -> game 1 rebuilt from its replay; titles use each player's most-played character |
| #60 | Quit-out on last stock mid-set; GF + reset back to back; OBS audio missing for 24 min; dock setup renamed mid-set; rclone signed in to the wrong Google account (403) | quit-out rule + flagged players; back-to-back split; `replay_games`; dock name auto-mapping; hands-off autopilot; account check before uploads |

## 7. Ideas not built yet

- A "clock mark" button in the Melee dock (`event: "clock_mark"` with the in-game timer in a note) would make the
  stream calibration exact without the audio match. Old readers skip unknown events, so it's safe to add.
- Read the dock's Main Setup segments as a cross-check for "on stream" (since #60 a Main Setup segment always
  means the set was on the overlay).
- One fixed drop spot per tournament for both docks' `timestamps\protocol-N\` folders, with one naming style
  (`Protocol-N` vs `Protocol #N` today; the autopilot accepts both).
- Ultimate: stop with a clear message when `log.jsonl` is missing (it currently reads as an empty night).
