# Stock icons: provide your own

The Melee stock icons are Nintendo / HAL art, so none are included. Put your own icon set here, one PNG per
character + costume colour, named exactly `"<color> <Character>.png"` (lower-case colour, a space, the
character's name as below). Square PNGs with a transparent background; any size works (OBS and the VOD
renderer scale them into the `stock` box from `layout.json`; the classic in-game icons are 24x24).

Who uses them:

- **The dock**: the character picker and the On stream panel show them; when a character is set on stream the
  dock copies the right file to `output\playerN_stock.png`, which OBS shows ("P1/P2 stock icon").
- **The VOD renderer** (render PC): reads this folder as `tools\render\docks\melee\assets\stock_icons\` for the
  stock icon on rendered sets.

Without them everything still works: the picker shows the names instead of pictures, OBS shows nothing in the
stock icon spot, and the renders draw no icon. A missing colour only affects that colour.

Use icons you have the right to use (your own drawings, or a set your community shares for streaming).

## File names the dock looks for (26 characters, 123 files)

`neutral` is the default costume. The colours per character are the `CHARACTERS` table at the top of
`static\dock.js` (edit it there if your set names a colour differently).

| Character | Files |
|---|---|
| Bowser | `neutral Bowser.png`, `red Bowser.png`, `blue Bowser.png`, `black Bowser.png` |
| Captain Falcon | `neutral Captain Falcon.png`, `black Captain Falcon.png`, `red Captain Falcon.png`, `white Captain Falcon.png`, `green Captain Falcon.png`, `blue Captain Falcon.png` |
| Doctor Mario | `neutral Doctor Mario.png`, `red Doctor Mario.png`, `blue Doctor Mario.png`, `green Doctor Mario.png`, `black Doctor Mario.png` |
| Donkey Kong | `neutral Donkey Kong.png`, `black Donkey Kong.png`, `red Donkey Kong.png`, `blue Donkey Kong.png`, `green Donkey Kong.png` |
| Falco | `neutral Falco.png`, `red Falco.png`, `blue Falco.png`, `green Falco.png` |
| Fox | `neutral Fox.png`, `red Fox.png`, `blue Fox.png`, `green Fox.png` |
| Ganondorf | `neutral Ganondorf.png`, `red Ganondorf.png`, `blue Ganondorf.png`, `green Ganondorf.png`, `purple Ganondorf.png` |
| Ice Climbers | `neutral Ice Climbers.png`, `green Ice Climbers.png`, `orange Ice Climbers.png`, `red Ice Climbers.png` |
| Jigglypuff | `neutral Jigglypuff.png`, `bow Jigglypuff.png`, `crown Jigglypuff.png`, `flower Jigglypuff.png`, `headband Jigglypuff.png` |
| Kirby | `neutral Kirby.png`, `yellow Kirby.png`, `blue Kirby.png`, `red Kirby.png`, `green Kirby.png`, `white Kirby.png` |
| Link | `neutral Link.png`, `red Link.png`, `blue Link.png`, `black Link.png`, `white Link.png` |
| Luigi | `neutral Luigi.png`, `white Luigi.png`, `pink Luigi.png`, `blue Luigi.png` |
| Mario | `neutral Mario.png`, `yellow Mario.png`, `blue Mario.png`, `green Mario.png`, `brown Mario.png` |
| Marth | `neutral Marth.png`, `red Marth.png`, `green Marth.png`, `black Marth.png`, `white Marth.png` |
| Mewtwo | `neutral Mewtwo.png`, `red Mewtwo.png`, `blue Mewtwo.png`, `green Mewtwo.png` |
| Mr. Game & Watch | `neutral Mr. Game & Watch.png`, `red Mr. Game & Watch.png`, `blue Mr. Game & Watch.png`, `green Mr. Game & Watch.png` |
| Ness | `neutral Ness.png`, `yellow Ness.png`, `blue Ness.png`, `green Ness.png` |
| Peach | `neutral Peach.png`, `daisy Peach.png`, `white Peach.png`, `blue Peach.png`, `green Peach.png` |
| Pichu | `neutral Pichu.png`, `red Pichu.png`, `blue Pichu.png`, `green Pichu.png` |
| Pikachu | `neutral Pikachu.png`, `red Pikachu.png`, `blue Pikachu.png`, `green Pikachu.png` |
| Roy | `neutral Roy.png`, `red Roy.png`, `blue Roy.png`, `green Roy.png`, `yellow Roy.png` |
| Samus | `neutral Samus.png`, `pink Samus.png`, `green Samus.png`, `brown Samus.png`, `blue Samus.png` |
| Sheik | `neutral Sheik.png`, `red Sheik.png`, `blue Sheik.png`, `green Sheik.png`, `black Sheik.png` |
| Yoshi | `neutral Yoshi.png`, `red Yoshi.png`, `blue Yoshi.png`, `yellow Yoshi.png`, `pink Yoshi.png`, `cyan Yoshi.png` |
| Young Link | `neutral Young Link.png`, `red Young Link.png`, `blue Young Link.png`, `white Young Link.png`, `black Young Link.png` |
| Zelda | `neutral Zelda.png`, `red Zelda.png`, `blue Zelda.png`, `green Zelda.png`, `lavender Zelda.png` |
