# Backlog

Things asked for that aren't built yet, with enough context to pick up cold.

## Socket spacing — house convention

Implemented: the first socket sits **0.5" below the top** of the device block,
and every socket after it is **0.25" below the last**, per side. Sockets stack
from the top on a fixed pitch rather than spreading across the block's height,
so a tall device keeps the same spacing as a short one.

Sockets hang from the **header baseline** — local `y = 0`, where ConnectCAD's
name/make header meets the rectangle it was given. `CC_DeviceFromShape` adds the
header above your rectangle, so the top of the block is a header's height higher
and measuring from it puts the whole stack too high.

Stated in inches on the printed sheet, applied in document units × layer scale.
Document units are assumed to be inches: `GetUnits()` returns several values and
picking one by shape gave 25.0 on an inch drawing, multiplying every drop by 25.
The raw values are logged so the right field can be identified from evidence if
this ever needs to work in metric.

## Drawing preferences

Generated objects currently take whatever ConnectCAD defaults to. Two choices
should be the user's, not the tool's:

- **Circuit line mode.** The Circuit record's `CircuitType` field — a real job
  uses `rounded`; `CC_CircuitFromShape` hard-codes `polyline`. Whatever a
  generator draws should match the house style of the drawing it lands in.
- **Device label symbol.** The Device record's `symbol` field is the *label*
  symbol, not the body. ConnectCAD ships `dev_label_generic`, `EXT_L_label`,
  `EXT_R_label`, `TP_label`, `VDA_label`, `VJX_label`.

Both are per-drawing conventions, so they belong with the document profile
rather than in a global settings file — the profile already reads
`symbol` usage off the drawing, so the sensible default is "whatever this
drawing already uses most", with an override.

## Claude-powered generation

Blocked on nothing technical now — the creation probe confirmed devices,
sockets and wiring all work from script. Remaining pieces:

- **PDF input with page selection.** A drawing set is mostly location plans;
  only the AV-4xx signal-flow sheets are worth sending. Each page costs roughly
  5–9k input tokens as an image, so the user picks pages rather than submitting
  a whole file.
- **Device database lookup.** `Libraries/Defaults/ConnectCAD/ConnectCAD_Database/
  ConnectCAD Devices DB.txt` is tab-delimited, ~17k rows, and carries the real
  socket set for each make/model. Looking a device up beats letting a model
  invent its sockets.
- **Layout is wiring.** `ConnectSelected` pairs sockets by horizontal alignment,
  so a generator's job is placement, not netlisting.

## Smaller things

- Move **Export Reference Schematic** and **Creation Probe** out of the main
  launcher — they are setup and diagnostic tools, not everyday drafting ones.
- The six unnamed power-distribution devices in the Geffen drawing are invisible
  to every tool that works on names. Naming them is a drawing task, but the
  tools could offer to.
