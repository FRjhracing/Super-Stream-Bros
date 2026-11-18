# Stream laptop handoff strategy

Written 2026-11-17 on the stream laptop (project `%USERPROFILE%\Documents\SuperStreamBros`).
Counterpart to `Render PC handoff strategy.md` (same SSD root). That file says how the render PC **uses**
the data; this one says how the docks and the laptop-side workflow **produce** it right now, what changed
functionally since the render PC last synced, and answers to its section 5 ideas. The exact data formats
are in `RENDER_PC_HANDOFF.md` (laptop project folder, updated 2026-11-11; copy it over if the render PC's
copy is older). Nothing here changes a format beyond what that file already says.

---

## 1. What the laptop side produces each week

| Output | Made by | Where it is on the laptop | How it reaches the SSD |
|---|---|---|---|
| Melee stream recording `YYYY-MM-DD HH-MM-SS.mp4` | OBS (collection "Protocol Dock") | `%USERPROFILE%\Videos\Main OBS Out\` (OBS output path; #59 was recorded to `P:\MeleeRecordings\`) | "Stream PC handoff" skill -> `MeleeRecordings\Protocol-N\` |
| Melee `setups.jsonl` (+ `setups.csv`, `Setup times.txt`) | Melee dock, port 8765 | `Super Stream Bros Melee\timestamps\protocol-N\` | same skill, same folder |
| `.slp` replays | **not the laptop any more (2026-11-17):** the render PC uploads the setup flash drives itself | - | - |
| Ultimate recordings, `log.jsonl`, `setups.jsonl`, `characters.json`, `player_characters.json` | Ultimate TO's PC + Ultimate dock, port 8766 | TO's `timestamps\protocol-N\` | TO copies to `UltimateRecordings\` |

Not needed on the render PC (agreeing with your section 5): `player_prefs.json`, `dock_state.json`,
`dock_config.json`, `setup_state.json`. Stop copying them. The one useful bit of `dock_config.json` is the
setup list, and every name in it already appears in `setups.jsonl` as `setupName`.

---

## 2. Functional dock changes since the render PC's last sync (all live from #60, 2026-11-16)

Format-level changes are spelled out in `RENDER_PC_HANDOFF.md` section 0. In short:

### Melee dock (`Super Stream Bros Melee\`)
1. **One segment per set on a re-report.** Reset + report again no longer writes a second backdated `on_setup`.
   It appends another `set_end` with the same `seg` (last one counts; its `t` repeats the first end on purpose)
   and, if the TO picked another setup, a `setup_fix` (also by `seg`). Sort ends by file order / `id`, not by `t`.
2. **Bracket restart on start.gg:** sets on a setup at the restart get `set_end` with
   `reason: "bracket restarted"` and no result: discard those segments. Segments whose numeric `setId` isn't in
   the final bracket come from before a restart: discard (flag if the same pairing has only a zero-length
   "setup picked at report" segment afterwards).
3. **Bracket start burst:** the first "Put on setup" of the night starts the bracket; sets put on setups in the
   next ~minute are logged with `preview_…` ids at the right time. Match by identifier + both players.
4. **Put on setup -> Main Setup now always = Put on stream** (overlay + start.gg stream assignment). So a Main
   Setup segment means the set really was on the overlay/stream, whichever button the TO used.
5. **Overlay clears itself when the on-stream set finishes** (reported in the dock or on start.gg), and when the
   live set is moved to an off-stream setup. Effect on the recording: between sets the overlay shows blank
   names / default pictures / 0-0. Relevant if you ever read the overlay off the video.
6. **Home, Full Bracket and the new Active Bracket page share one start.gg fetch,** so the TO sees reports a few
   seconds sooner and the 20 s poll's "reported" ends land closer to the real time.
7. **Rate limit / query size fixes** (25 sets per page, under 55 reads/min). Before this, a 429 or "complexity
   too high" error could stall the poll and delay `set_end` lines. Fewer of those delays from #60 on.
8. Touch-screen UI (set window, tabs, Completed sets tab with Reset). Display only, no file effect.

### Ultimate dock (`Super Stream Bros Ultimate\`)
- Brought level with the Melee dock on 2026-11-11: items 1-3 and 6-8 above, plus restart detection also ends the
  `log.jsonl` recording entry (`set_end`, `reason: "bracket restarted"`). A re-report is corrected in
  `setups.jsonl` only; `log.jsonl` keeps the first result, so take results from `setups.jsonl` or start.gg.
- **Open:** it is not confirmed that the TO ran the 2026-11-11 build on #60. `P:\Ultimate Dock\` is still the
  2026-11-02 build. A night's log is from the new build if it has `setup_fix` lines or `re-reported in dock`
  ends; their absence proves nothing (no re-reports that night).

---

## 3. #60 status (2026-11-16) from the laptop side

Melee
- **Copied 2026-11-17** to `MeleeRecordings\Protocol-60\`: `2026-11-16 19-28-48.mp4` (3.66 GB, MD5 verified),
  `setups.jsonl`, `setups.csv`, `Setup times.txt`. Replays: upload from the flash drives on the render PC.
- Dock log: 4 setups:
  `Main Setup`, `Bzimm's Setup`, `BJH`, `Big TV`. 17 sets, all with a result, no re-reports, no `setup_fix`,
  no restart.
- First Main Setup set (E) went on at 19:32:38, after the recording start (19:28:48): no clamping needed.
- Quirk to check: **Grand Final (I)** 21:02:12-21:21:58 `egg 3-0 Uncle B`, then **Grand Final Reset (J)**
  21:22:04-21:22:14 (10 s) `egg 3-0 Uncle B`. 20 minutes is long for a 3-0, so both sets were most likely
  played inside I's segment and J was put on and reported right after. Expect up to 6 games on Main Setup in
  I's window; split them by start.gg's scores (I first, then J).
- Setup names: "Big TV" is the dock name for the Wii that had the 2025 date. "Bzimm's Setup" vs the Drive
  folder name: map in `vod_config.json` as before.

Ultimate
- `UltimateRecordings\Protocol #60\` has the recording, `characters.json`, the chapter/setup `.txt` files,
  but **no `log.jsonl` / `setups.jsonl`** (as you found). We'll ask the TO for their
  `timestamps\protocol-60\` folder. Until then, `Recording 1 chapters.txt` is the fallback.

---

## 4. Answers to the render PC's section 5 ideas

| Idea | Laptop-side answer |
|---|---|
| Cutter estimates each setup's Wii offset from dock windows | Good fit: dock and recording share the laptop clock, so dock windows are a clean reference. Since #60 the windows are tighter (fewer poll delays, re-reports no longer add backdated starts). No dock change needed for this. |
| Dock logs a "GO"/clock-sync moment for Main Setup | Not built. Possible as a one-button line in `setups.jsonl` (e.g. `event: "clock_mark"`, `setup`, `t`, optional `note` with the in-game timer). Unknown events are already skipped by the contract, so adding it wouldn't break old readers. Needs a decision from the user. |
| Use Main Setup segments as a cross-check for "on stream" | Supported: since 2026-11-11 a Main Setup segment always means the set was put on stream (item 4 above). Sets moved to Main Setup mid-set end their old segment with `moved to Main Setup`. |
| Don't copy `player_prefs.json` / overlay state | Agreed (section 1). |
| Ultimate: stop with a clear message when `log.jsonl` is missing | Agreed (render PC side). On our side: the TO's `SETUP.txt` should say to copy the whole `timestamps\protocol-N\` folder, not just the `.txt` files. |
| Ultimate: missed sets hurt more than late clicks | Matches what the dock does: "Put on recording" logs first and only then talks to start.gg, so a slow start.gg can't drop a click. Missed sets are TO habit (busy in top 8); no dock change planned yet. |
| Fixed drop spot per tournament on the SSD | Proposed layout (not yet agreed with the user): `MeleeRecordings\Protocol-N\` = recording + the dock's `timestamps\protocol-N\` contents (`setups.jsonl`, `setups.csv`, `Setup times.txt`); `UltimateRecordings\Protocol #N\` = both recordings + the TO's whole `timestamps\protocol-N\` folder. The folder names differ (`Protocol-N` vs `Protocol #N`); the cutters should accept both, or we standardise on one. |

---

## 5. Weekly laptop-side routine (from 2026-11-17)

- After the night: run the **"Stream PC handoff"** skill on the laptop (`/stream-pc-handoff`). It copies the
  Melee recording + `setups.jsonl`, `setups.csv`, `Setup times.txt` to `MeleeRecordings\Protocol-N\`, never
  overwrites, checks the MD5, and lists log quirks. It skips the dock state files, replays and Ultimate.
- Replays: uploaded from the flash drives **on the render PC**, which works off this SSD.
- Melee dock: no more functional changes planned (no bugs found on #60). The formats in
  `RENDER_PC_HANDOFF.md` are stable.
- Ultimate dock: the Melee UI makeover will be ported later (not scheduled). When it is, re-ship the zip and
  confirm the TO is running it; check `RENDER_PC_HANDOFF.md` section 0 for any log changes.
