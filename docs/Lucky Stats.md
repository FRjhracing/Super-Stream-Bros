# Lucky Stats set generation

[Lucky Stats](https://luckystats.gg) publishes tournament sets with their replays and per-game stats. Each
PROTOCOL Melee event gets an event page (e.g. #58 `luckystats.gg/event/310766`, #59 `.../316304`,
#60 `.../323683`) with one page per set, and the YouTube videos link to it.

## Credit: the format comes from auto-vlerk-game-data-mapper

The set folder format, and in particular `context.json`, follows **`buildContext` in
[0xburn/auto-vlerk-game-data-mapper](https://github.com/0xburn/auto-vlerk-game-data-mapper)**, the open-source
tool that maps a tournament's Slippi replays to its start.gg sets for Lucky Stats. All credit for the format goes
to that project. `luckystats_export.py` writes the same structure, so Lucky Stats accepts our uploads as if that
tool had made them.

**Why not run that tool directly?** It maps games to sets using start.gg's per-game reports (characters and
winners per game). PROTOCOL's sets are reported as a final score only, and the Wiis' replays have no Slippi
identities (console replays carry no connect codes, and in-game nametags follow the controller, not the player).
So the mapping can't be made from start.gg alone. Instead the games come from the VOD cutter's reviewed
`plan.json`, which already matched every start.gg set to its replays (setup, timing, scores, characters).
`luckystats_export.py` only turns that plan into the mapper's output format.

## What gets generated

```
LuckyStats\Protocol #N\
  sets\
    set-<start.gg set id>\
      01.slp, 02.slp, ...      copies of the set's games in play order (originals untouched)
      context.json
  zips\
    set-<start.gg set id>.zip  the same files at the zip's root: what you upload
```

`context.json` (fields as in the mapper's `buildContext`):

| Field | Meaning | Where our value comes from |
|---|---|---|
| `bestOf` | 3 or 5 | `max(score) * 2 - 1` (first to 2 or 3) |
| `startMs` | set start, epoch ms | game 1's **corrected** time (Wii clock + the setup's offset), since the Wii clocks are wrong |
| `scores` | one entry per game: both slots' score **before** that game | replay winners, counted game by game |
| `finalScore` | the slots after the last game | must equal start.gg's score, else the export stops |
| `players` | `entrant1/2`: name + characters used, in order of first use | start.gg tag + replay characters (Lucky Stats / slippi-js names, e.g. "Dr. Mario") |
| slots | `displayNames`, `prefixes`, `pronouns`, `ports`, `score` | start.gg tag/prefix, the player's replay port |
| `startgg` | tournament id/name, event id/name, set id + `fullRoundText` | start.gg API |
| `mapping` | `generatedBy: "protocol-vod-cutter"`, `version`, `evidence`, `files` (name + sha256) | the copied files' hashes |

## How to run it

After `vod_cutter.py plan` (or the autopilot, which does all of this itself):

```
python tools\python\luckystats_export.py "<SSD>\Protocol VOD\Melee\Protocol #N\plan.json" "<SSD>\Protocol VOD\Melee\Protocol #N\replays" "LuckyStats\Protocol #N\sets"
```

- Sets with a doubtful flag in the plan are skipped and listed (video-only flags, like "recording started late"
  or "games rebuilt from the replay", don't count).
- Already-exported sets are skipped, so re-running is safe; delete a set's folder to redo it.
- `--repaired <dir>`: games repaired with `slp_repair.py` are taken from that folder.
- Zip each set folder with the files at the root (the autopilot does this; by hand: select the files inside the
  folder, not the folder, and "Send to > Compressed folder").

**When to export**: right after a confident plan, without waiting for the render. Wait only when the plan has
doubtful sets.

## Uploading and links

1. Upload the zips on Lucky Stats' upload page (browser; there's no upload API).
2. Lucky Stats numbers the sets itself. Copy the **event** link (and per-set links if you want them).
3. Put them in `vod_config.json`: `"luckystats": {"_event": "<event URL>", "<set letter>": "<set id or URL>"}`.
4. `python tools\python\vod_cutter.py kit <config>` then `python tools\python\youtube_upload.py tags <folder>`
   (already-uploaded videos get the links), or `youtube_upload.py links <folder>` to add only the event link to
   the live descriptions and the playlist. Sets without their own link point at the event page.

Notes from experience:
- **Re-uploading a set replaces it** (same start.gg set id = same Lucky Stats set). Fix the export and upload again.
- Lucky Stats takes the set **score** from start.gg and a re-upload does not refresh it: fix the score on start.gg
  *before* uploading, or ask the Lucky Stats admins to re-sync.
- luckystats.gg rate-limits scripted page fetches (HTTP 429), so links are pasted, not scraped.

## Replay retention

Lucky Stats now hosts the replays, so:
- Delete the local copies (`<SSD>\Protocol VOD\Melee\Protocol #N\replays\`, `LuckyStats\Protocol #N\`) once the
  Lucky Stats upload is verified. Keep `plan.json`, `review.md`, `vod_config.json`.
- Google Drive (`SSBM Replay Storage\Protocol #N`) is the fail-safe: delete it by hand at 2 weeks old, then run
  `youtube_upload.py links <folder>` so the videos and playlist stop linking the dead Drive folder.
