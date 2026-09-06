# Backlog

Things asked for that aren't built yet, with enough context to pick up cold.

## Socket spacing — ConnectCAD's own rule

Layout is no longer hard-coded inches. ConnectCAD derives every distance from
the **schematic grid** `(gx, gy)` times an integer count from Device Builder
preferences: socket pitch is **one grid unit**, the first socket sits
**(top space + 1) units** below the insertion point, minimum width is **6 grid
spaces**. On a 0.25" grid that is exactly the 0.25" pitch and 0.5" first drop
these drawings use — so the convention is ConnectCAD's default, expressed in
inches, and deriving it keeps the drawings right while surviving a different
grid.

The grid comes from the `ConnectCAD Settings...` record, falling back to the
document grid preferences (selectors 78/79), then to a stated default. The
Device Builder preference block itself is serialised on the Device record
format and is **not reachable from script**, so the stock counts
(min width 6, top 1, bottom 0, group gap 0) are constants here — a drawing
whose Device Preferences differ needs them changed to match.

## Build devices from symbols — done

A ConnectCAD **device symbol** is a symbol definition holding one fully-built
Device with its sockets already in the profile group. `place_device_from_symbol`
is a port of `Utilities::PlaceObjectFromSymbol`: find the Device inside the
definition, duplicate it onto the layer, copy across records the duplicate
lacks, reset, position.

Stamping one computes **no layout at all** — no grid, no pitch, no header
baseline — and matches house style by construction, because the symbol came from
a device somebody drew by hand.

`device_symbol_catalogue()` lists every device symbol in the document with the
make and model of the Device inside it, and `find_device_symbol(make, model)`
matches forgivingly on case, spaces, hyphens and underscores, since the same
product is written `Galaxy 408`, `GALAXY-408` and `Galaxy_408` across a set.

**To make a symbol:** build a device the way you want it, then *Save as Symbol…*
in its Object Info palette.

Device symbols live in the symbol folder **`zConnectCAD db Created`**, which is
where ConnectCAD files the ones it builds from the database. The Resource
Manager **root** holds device *parts* — jacks, terminals, patch points — which
are Device plug-in objects too, so a root-only search returns the wrong things
and misses every real device.

Still to do:
- Search ConnectCAD's shipped device libraries on disk, not just the open
  document.
- Fall back to the device database (`ConnectCAD Devices DB.txt`, ~17k rows) for
  the socket list when no symbol exists, so a hand-built device still gets its
  real connectors rather than invented ones.

## Drawing preferences

**Done.** `CC Tools > Preferences` writes `~/Documents/CC Tools/preferences.json`
and covers column spacing, row spacing, section gap, circuit line mode and the
device label symbol. Spacing is in printed inches and is scaled by the layer.

Still open: the label-symbol field is a free-text box, because the list of
symbols ConnectCAD ships has not been confirmed against this install, and the
header height a different label symbol produces would move every socket.

Original note:

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


## Verified ConnectCAD internals (2026-09-06)

Established by disassembling `connectCAD.vwlibrary/Contents/MacOS/connectCAD`
and reading the shipped data files. Each of these was checked against the
primary source a second time by a separate pass, and several first attempts
were wrong -- so treat anything NOT listed here as unverified.

**Circuit line mode.** `CircuitType` has exactly four legal values, all
lowercase: `polyline` (ConnectCAD's default), `rounded`, `chamfer`, `arrow`.
Bounded by a four-entry jump table in `ConnectTool_EventSink::GetCircuitType`.
`SetRField` alone does nothing -- the value is consumed in the PIO reset
handler, so `ResetObject` is required and sufficient. `CC_CircuitFromShape`
does hard-code `polyline`, and does it with exactly SetParamString +
ResetObject, so that sequence is sanctioned rather than a workaround.

The first three share one computed route polygon and differ only in corner
rendering. `arrow` is a different object -- paired stubs linked by
`__Arrow_ID`, gated on `__SameLayer` -- so it must never be written onto an
existing routed circuit.

**Circuits are auto-classed by signal.** `CC-Circuit-Signal-<SIGNAL>`, built in
`CClassHandler::GetSignalClassIID`. It happens ONCE, gated on the hidden
`__Version` parameter (reclass runs only while `__Version <= 2599`, then it is
stamped 2600). After that first reset your own class, line weight and colour
survive further resets. **Devices are not auto-classed** -- 61 SetObjectClass
call sites and the device reset handler is not among them -- so a device's
class is yours to set.

This is very likely how a schematic gets divided by signal type: class
visibility per viewport, not spatial regions. It would explain why the Geffen
drawing has all 212 devices in one continuous field with no spatial banding.

**Device label symbol.** The Device PIO declares six in `cCADDeviceObj.vwstrings`
(`dev_label_generic`, `EXT_L_label`, `EXT_R_label`, `TP_label`, `VDA_label`,
`VJX_label`); `Libraries/Defaults/ConnectCAD/Device/Device Labels.vwx` indexes
eight symbols. The label is placed at device-local (0,0) with UNIFORM scale
from the hidden `__gridScale` param. Swapping it is `Utilities::ChangeDevLabelSymbol`,
which is reached only from the OIP/tool path -- so a plain `SetRField` on
`symbol` is NOT the whole operation and is still unproven from script.

**Device database.** `Libraries/Defaults/ConnectCAD/ConnectCAD_Database/ConnectCAD Devices DB.txt`,
935,657 bytes, 24 tab-separated columns, **2,735 device records over 17,127
lines** (the 17k figure is lines, not devices). A device owns a block: it
starts where col0 or col1 is non-empty and runs to the next such row. Each
following row is a socket SERIES, not one socket -- col15 is a quantity, and
the suffix ConnectCAD appends is a single space then the number
(`CDeviceDBHandler::DecodeSocket`). Col16 orientation is only ever `L` or `R`.
Read it as bytes and split on `\r\n`: Python universal newlines corrupts it.

A companion `SignalTypes.txt` (UTF-8, CRLF, 1 header + 79 rows) defines the
signal vocabulary, and the DB's signals are a strict subset of it. Note the
app and user copies use DIFFERENT line terminators.
