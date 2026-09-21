# Backlog

Things asked for that aren't built yet, with enough context to pick up cold, and
a record of things settled so they aren't revisited. Verified ConnectCAD
internals live in [DESIGN.md](DESIGN.md).

## Open

### PDF input with page selection

A drawing set is mostly location plans; only the AV-4xx signal-flow sheets are
worth sending. Each page costs roughly 5–9k input tokens as an image, so the
user picks pages rather than submitting a whole file. Attaching a PDF to a chat
already works — what is missing is any way to get the reply back automatically,
which is the one thing the copy-paste route genuinely cannot do.

### Device label symbol is free text

The Preferences field is a text box, not a dropdown, because swapping the label
goes through `Utilities::ChangeDevLabelSymbol` — reachable only from the OIP
path, so a plain `SetRField` on `symbol` is not the whole operation and is
unproven from script. A different label symbol also changes the header height,
which socket placement measures, so the dropdown needs both facts settled.

ConnectCAD declares six in `cCADDeviceObj.vwstrings` (`dev_label_generic`,
`EXT_L_label`, `EXT_R_label`, `TP_label`, `VDA_label`, `VJX_label`);
`Libraries/Defaults/ConnectCAD/Device/Device Labels.vwx` indexes eight.

### Elbow stagger is inferred

`ControlPoint03X` as the elbow distance comes from two samples in a real
drawing. It matches both and nothing else obvious explains them, but it has not
been read out of the binary or checked visually in a generated drawing. Worth
confirming before relying on it for a dense fan-out.

### Smaller

- Move **Export Reference Schematic** and **Creation Probe** out of the main
  launcher — setup and diagnostic tools, not everyday drafting ones.
- The six unnamed power-distribution devices in the Geffen drawing are invisible
  to every tool that works on names. Naming them is a drawing task, but the
  tools could offer to.
- Device Builder preference counts (min width 6, top 1, bottom 0, group gap 0)
  are constants, because that preference block is serialised on the Device
  record format and is **not reachable from script**. A drawing whose Device
  Preferences differ needs them changed by hand.

---

## Settled

### Socket spacing comes from the grid

Not hard-coded inches. ConnectCAD derives every distance from the **schematic
grid** `(gx, gy)` times an integer count: socket pitch is **one grid unit**, the
first socket sits **(top space + 1) units** below the insertion point, minimum
width is **6 grid spaces**. On a 0.25" grid that is exactly the 0.25" pitch and
0.5" first drop these drawings use — so the convention is ConnectCAD's default
expressed in inches, and deriving it survives a different grid.

The grid comes from the `ConnectCAD Settings...` record, falling back to the
document grid preferences (selectors 78/79), then to a stated default.

### Devices are built from symbols first, database second

A ConnectCAD **device symbol** is a symbol definition holding one fully-built
Device with its sockets already in the profile group. `place_device_from_symbol`
ports `Utilities::PlaceObjectFromSymbol`: find the Device inside the definition,
duplicate it onto the layer, copy across records the duplicate lacks, reset,
position. Stamping one computes **no layout at all** — no grid, no pitch, no
header baseline — and matches house style by construction.

`device_symbol_catalogue()` lists every device symbol in the document with the
make and model inside it; `find_device_symbol()` matches forgivingly on case,
spaces, hyphens and underscores, since the same product is written
`Galaxy 408`, `GALAXY-408` and `Galaxy_408` across a set.

Symbols live in **`zConnectCAD db Created`**. The Resource Manager **root** holds
device *parts* — jacks, terminals, patch points — which are Device plug-in
objects too, so a root-only search returns the wrong things and misses every
real device. To make one: build a device by hand, then *Save as Symbol…* in its
Object Info palette.

**The database fallback is built.** When no symbol exists, `db_socket_specs()`
reads the real connector list out of `ConnectCAD Devices DB.txt` rather than
letting a model invent one. Format details are in DESIGN.md — note especially
that the number suffix is appended **verbatim**, so the trailing space in `MIC `
is the author's separator and not an artefact to strip, and that seventeen
make/model pairs collide once normalised and are merged by socket count.

### Stock symbol libraries are not searched, deliberately

`/Applications/Vectorworks 2026/Libraries/ConnectCAD/Device/` holds 346 entries.
**345 are 10-byte `.vwx.proxy` placeholders** — Luminex, Meyer, Shure, Crestron,
Extron, all of them — containing nothing but a numeric id. Exactly one real file
had been downloaded (`Crest.vwx`); the user library folder held none. Vectorworks
fetches these on demand through the Resource Manager, so a tool that searched
them would, on a normal install, find one manufacturer.

Ryan's call, and the better design: **do not rely on stock symbols at all** —
they are inconsistent between manufacturers even once downloaded. Look the device
up and keep the answer in a curated file so it stays consistent. That is the
device list at the end of `JOB-SPEC.md`, which carries dimensions, weight, power
draw, and rack mounting with rack U.

Symbols already in the **open document** are still used and still preferred —
house-made and demonstrably correct. The argument above is only about stock.

### How a schematic divides

Confirmed with Ryan, 2026-09-06, after two wrong guesses.

**Circuits carry the class; devices do not.** ConnectCAD files every circuit in
`CC-Circuit-Signal-<SIGNAL>` and a sheet viewport filtered to one of those
classes is that signal's drawing. The `CC-Device-*` classes ConnectCAD ships are
not device classes at all — they are part classes for components *inside* a
device PIO (`-Graphics`, `-DisplayTag`, `-Description`, `-Location`,
`-PanelName`, `-ExternalName`).

So the tool must not class devices, and `apply_signal_class` is only ever called
on circuits. Two wrong ideas, recorded so they aren't revisited:

- *Class devices by section.* Wrong — nothing in ConnectCAD does this, and a
  device belongs on every sheet its circuits appear on.
- *Drop spatial banding in favour of classes.* Wrong — not alternatives. Classes
  divide the **signals**; spatial regions are why a device is drawn again in each
  section, so each region has its own block for its own circuits.

The Geffen drawing shows no gaps between regions, which is what suggested there
were none. Contiguous regions of a dense field are still regions; the drafter
simply left no space. `section_gap_inches` exists so generated work can, or
need not.

### Alignment was never required — the staircase is gone

An early note claimed `ConnectSelected` pairs sockets by horizontal alignment.
**It does not** — the function contains no floating-point comparison at all, and
a probe wired three circuits offset by 0.10", 0.85" and 1.60" without complaint.
Pairing is by column membership and Y order; see DESIGN.md.

An `align_to` mechanism and a staircase layout were built on the false premise
and shipped. The staircase made nineteen circuits graze the device in the
previous column and drawings four times wider than needed — 35" fell to 7" once
removed. The note was inherited and never tested against the binary or a
drawing, which is the whole lesson.

### Drawing preferences

`CC Tools > Preferences` writes `~/Documents/CC Tools/preferences.json`: column
spacing, row spacing, section gap (0 by default), circuit line mode, device label
symbol. Spacing is in printed inches and is scaled by the layer.

### The Claude API client — deleted

`claude_request`, `load_claude_config`, `usage_totals`, `format_usage` and the
first-run key prompt were defined and never called. No tool was wired to them, so
none of it had ever run: not the key handling, not the usage log, not the cost
accounting. Deleted 2026-09-06, 333 lines, on Ryan's call.

It predated the copy-paste route, and copy-paste turned out to be the better
answer for this audience — no key, no account, no billing. Untested network code
in a plug-in that edits live drawings is a liability, not an asset, and git
remembers it. If it is ever wanted back, the case is the PDF path above; recover
it from history rather than rewriting it, and test it before trusting it.

### The audit — 23 findings, all fixed

A six-dimension adversarial review of the whole plug-in, after find-and-replace
was found to break links. Everything it caught is fixed and covered by tests --
one adversarial pass over one version, not a proof of correctness. The
structural lessons are written into DESIGN.md rather than repeated here. The
themes, so the same classes of bug get looked for next time:

- **Renames that write the field instead of calling the rename.** The stored
  Device↔Equipment association survives a `SetRField` pointing at the old match.
- **A second field holding the same name.** `PanelConnector` names its socket in
  both `ConnectedSkt` and `SocketName`; syncing one is worse than syncing
  neither, because it looks done.
- **Objects `classify()` returned `None` for.** `Device-External` was invisible
  to Search, Spell Check and Replace alike while carrying editable free text.
- **Match keys that can be blank.** `""` matches every unnamed object.
- **Scope that isn't the scope.** Socket names are unique per device, not per
  document; equipment lives on layers the selection doesn't include.
- **Failures with no output.** A licence-gated no-op, a one-column selection, an
  unresolved reference — each previously did nothing and said nothing.
