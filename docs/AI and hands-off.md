# With and without AI

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

Every tool here is a plain Python script or a local web page. **Nothing requires an AI agent to run.** The
project was built with Claude Code (an AI coding agent in the terminal), and an agent is still the fastest way
to handle the unusual weeks: reading `review.md`, spotting a wrong clock, writing an override, explaining a
quirk, or changing the code when a new kind of problem turns up. This page says what each job needs, and how
to run the Melee VOD work completely hands-off.

## What each job needs

| Job | Without AI (scripts + a person) | With an AI agent (Claude Code) |
|---|---|---|
| Run the bracket, overlay and setup log on the night | Melee Stream Dock in OBS (buttons) | same; the agent isn't involved live |
| Hand the recording + dock log to the SSD | copy 4 files by hand (Weekly workflow) | "Stream PC handoff" skill on the Stream PC: copies, checks MD5, lists log quirks |
| Get the replays off the flash drives | `slippi_uploader.py` + plug in each drive (always a person) | same; the agent can watch the upload and recover from Google errors |
| Write `vod_config.json` | copy last week's and edit, or let `ssb_autopilot.py` write it | the agent writes it |
| Wii clock offsets | `ssb_autopilot.py` estimates them; by hand: in-game timer on stream + dock windows | the agent checks them and explains outliers |
| Match sets to replays | `vod_cutter.py plan` (or the autopilot) | same, plus the agent reads `review.md` and asks about doubtful sets |
| Decide doubtful sets (missing games, wrong scores, odd characters) | read `review.md` / `NEEDS_REVIEW.md`, ask the players, edit `"sets"` overrides | the agent proposes the override and the question to ask |
| Render | `vod_cutter.py render` (or the autopilot) | same; the agent can restart a frozen render and check audio/cuts |
| Stream audio dropouts | the autopilot finds digital silence and rebuilds those games | the agent also catches non-silent problems you tell it about |
| Upload to YouTube | `youtube_upload.py upload <folder>` | same, plus checks the channel/account first |
| Lucky Stats export | `luckystats_export.py` (the autopilot does it and zips) | same |
| Lucky Stats upload | browser upload of the zips (always a person) | - |
| Lucky Stats links in video descriptions | put the event URL in `vod_config.json`, run `vod_cutter.py kit` + `youtube_upload.py tags` | the agent does it from the link you paste |
| Remove dead Drive links later | `youtube_upload.py links <folder>` once the Drive folder is deleted | the agent checks at the start of each session |
| Ultimate VODs ★ | `ultimate_cutter.py plan/render/kit`; missed sets need someone to watch the recording | the agent builds contact sheets, proposes cuts, writes the TO's questions |
| Next week's start.gg tournament, Discord posts | by hand on start.gg / Discord | agent skills: `protocol-weekly-rollover`, `announce-tonight` (start.gg setup + posts); `superstreambros-test-reset` resets the dock test bracket |
| Seasonal themes (art + round names) | design in an image editor, write `theme.json` | the agent can script layered art (Pillow) and write the theme |
| Per-player set analysis | `slp_analyze.py` gives JSON numbers | the agent turns them into a write-up and clip pairs |
| New edge cases | a developer changes the code | the agent changes the code and the notes |

Skills are reusable instructions stored in the user's Claude account; they are not part of this package.

## The hands-off path: `ssb_autopilot.py` ★

```
python tools\python\ssb_autopilot.py 61            plan + checks, then Lucky Stats zips + render + kit
python tools\python\ssb_autopilot.py 61 --upload   ... and upload to YouTube
python tools\python\ssb_autopilot.py 61 --plan-only
```

It does what used to need a person or an agent:

| Step | How |
|---|---|
| Find the inputs | `MeleeRecordings\Protocol-N\` (or `Protocol #N`): the largest OBS recording + the dock's `setups.jsonl`; replays in the tournament folder |
| Write the config | from last week's (stream setup, channel, titles); keeps anything a person already set |
| Wii clock offsets | estimated per setup from the dock windows, wrong year included; confidence per setup |
| Stream clock | one short stream game rendered from its replay, its audio located in the stream recording (two games must agree) |
| Renamed dock setups | mapped to the replay folder where their sets were found, then re-planned |
| Stream audio dropouts | digital silence in the recording over a stream game -> that game rebuilt from its replay |
| Back-to-back sets | split by report order (in `vod_cutter.py` itself) |
| Confidence gate | stops with `NEEDS_REVIEW.md` (exit code 2) instead of rendering when anything needs a person |
| Output | Lucky Stats sets + zips, all videos, upload kit, optional upload |

Re-run it after fixing what `NEEDS_REVIEW.md` lists: it keeps every hand edit in `vod_config.json` (offsets you
set by hand are never replaced; `--keep-offsets` keeps all of them).

### What still needs a person (always)
1. **Plugging in the flash drives** (`slippi_uploader.py`). Physical.
2. **The Stream PC handoff** copy, unless you script it (e.g. a `robocopy` of the recording folder and the dock's
   `timestamps\protocol-N\` to the SSD at the end of the night).
3. **`NEEDS_REVIEW.md` items**: the old "review folder" step. It replaces holding doubtful sets in a review folder
   for the TO; now the run simply stops before rendering and lists what to decide.
4. **Lucky Stats upload** in a browser, then pasting the event link into `vod_config.json` (no API).
5. **Publishing on YouTube**: API uploads stay Private until the Google project passes YouTube's audit
   (`guides\03 YouTube API audit form.html`).
6. **Google sign-ins** when a token expires (browser), and fixing it when rclone is signed in to the wrong account.
7. **Ultimate**: `ultimate_cutter.py` runs unattended, but sets the dock missed must be found by watching; those
   videos are held private with questions for the TO.

### What makes it stop (blocking)
- A completed start.gg set with no run of games that fits (wrong offset, missing replay, wrong score on start.gg).
- Replays that disagree with start.gg's score.
- A doubtful clock offset on a setup that has sets.
- The dock put a set on one setup but the games fit only on another.
- A dock setup name with no replay folder after auto-mapping.
- An unreadable replay.

### Known limits (it carries on, and may be wrong)
- **Ambiguous picks**: when two runs fit a set, it picks by the players' characters in their other sets and
  only notes it. Wrong only when two pairs of players have identical characters and scores at the same time.
- **start.gg is trusted** when the replays agree with it. A wrongly reported score that the replays happen to fit
  (rare) goes through.
- **Offsets** need dock windows; without them it uses start.gg times and usually stops as "doubtful". Two very
  different offsets that both fit stop the run too.
- **Stream calibration** needs two clean stream games (no silence, not at the recording's edges). Otherwise the
  cuts use the dock estimate (+-30 s) and the padding grows to 30 s.
- **Audio problems** are found only when the stream audio is digital silence. Crackle, a muted mic or wrong
  levels are not detected.
- **Picture problems** (OBS showing the wrong scene, a frozen capture) are not detected.
- **Dolphin freezes** are retried 3 times per game, then the render stops (re-run continues; finished games are cached).
- **New kinds of weirdness** (a new dock event, a set played across two setups, a mid-set port swap) aren't
  known: they stop the run at best, or slip through when they look normal.

### Running it on a schedule
The autopilot is safe to run repeatedly (it never overwrites replays, recordings or your edits). Windows Task
Scheduler can start `python tools\python\ssb_autopilot.py <N> --upload` the morning after, once the flash drives
have been uploaded; check `NEEDS_REVIEW.md` or the exit code (0 done, 2 needs review).

## Working with an agent (Claude Code)

- Open a terminal in the project folder and start Claude Code. `CLAUDE.md` (the agent's project guide; see
  `docs\reference\`) and the notes files give it the full context: rules, PCs, paths, weekly steps, past decisions.
- Keep the notes current: the agent records decisions in `PROJECT_NOTES.md` / `VODCUTTER_PROJECT_NOTES.md`, which
  is how the next session knows what was decided.
- Ask it to run the autopilot, then go through `NEEDS_REVIEW.md` with you.
- Interactive commands (Google sign-ins, `rclone config reconnect`) must be typed by you: in Claude Code, prefix
  them with `!` so the output lands in the conversation.
- The agent follows the same ground rules: replays and recordings read-only, no deletes on Drive, secrets never
  in files or chat.
