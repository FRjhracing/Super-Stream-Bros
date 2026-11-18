# Super Stream Bros Ultimate dock ★

> ★ = **beta**: used at our events but not thoroughly tested yet. Found a bug or something unclear? [Open an issue on GitHub](https://github.com/FRjhracing/Super-Stream-Bros/issues) (FRjhracing).

For the Ultimate TO: runs the Ultimate bracket on start.gg and logs **recording timestamps** (two recordings)
and which set was on which setup, so the render PC can cut the recordings into one video per set
(`tools\python\ultimate_cutter.py`). No stream overlay. Everything the TO needs to know is in **`SETUP.txt`**.

It is self-contained (no imports from the rest of the package), so it can be sent on its own.

## Shipping it to the Ultimate TO as a zip

Zip this folder as `Super Stream Bros Ultimate.zip` with only these files:

```
dock_server.py  lan.py  start_dock.bat  open_docks.bat  set_token.bat  SETUP.txt  characters.json  static\
```

Leave out (they are the sender's own data or test output): `dock_config.json`, `dock_state.json`,
`timestamps\`, `__pycache__\`, and `player_characters.json` unless you are sending the TO back their own copy.
PowerShell, from this folder:

```powershell
Compress-Archive -Path dock_server.py,lan.py,start_dock.bat,open_docks.bat,set_token.bat,SETUP.txt,characters.json,static -DestinationPath "$env:USERPROFILE\Desktop\Super Stream Bros Ultimate.zip"
```

Updating a TO who already has it: send only the changed files (usually `dock_server.py`, `lan.py` and `static\`), so their
`dock_config.json` and `player_characters.json` stay.

## Data files

| File | Shipped | What |
|---|---|---|
| `characters.json` | yes | start.gg's Ultimate cast (ids from videogame 1386), for the character picker in the report window |
| `player_characters.json` | no | grows as the TO reports sets: player id -> characters per set; pre-fills each player's usual characters. Ask the TO to send it back with the recordings so your copy stays current |
| `timestamps\<slug>\` | - | `log.jsonl` (recordings), `setups.jsonl`, `characters.json`, chapter lists, CSVs: copy the **whole** folder to the SSD after the night |

`player_characters.json` can start empty. To pre-fill it from past events, write a small script for your own
data source (PROTOCOL seeded it from its YouTube video titles).

## Big events and LAN ★

The same settings as the Melee dock (`port`, `tokenVar`, `lan` / `lanPin` / `lanViewPin`,
`bracketCacheSeconds`, `maxBracketPages`; env var `SSB_ULTIMATE_DOCK_PORT`): see
`guides\06 LAN and multi-TO events.html`. All off by default.
