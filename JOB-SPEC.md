# ConnectCAD schematic job — spec

**Give this file to Claude.** It tells Claude how to write a job file that the
CC Tools plug-in can draw in Vectorworks. Then describe the schematic you want,
and Claude replies with a `.json` file to download.

---

## Your job, Claude

Read this whole file. Then, from the user's description, produce **one JSON
file** and **offer it as a download** — not as a code block in the chat. The
user has to save it to disk and pick it in a Vectorworks file dialog, so a file
they can click is the deliverable. Name it anything ending in `.json`.

Ask about anything genuinely ambiguous before writing it. Signal types, socket
counts and rack locations are worth getting right; exact coordinates are not,
because the rules below determine those.

## Shape of the file

```json
{
  "devices": [
    {
      "name": "SWTCH 4.01 HL UPPER",
      "tag": "SWTCH 4.01 HL UPPER",
      "make": "Luminex",
      "model": "10i-IP",
      "column": 0,
      "sockets": [
        {"name": "LAN 1", "type": "OUT", "signal": "LAN", "connector": "EC-6A", "side": "R"},
        {"name": "LAN 2", "type": "OUT", "signal": "LAN", "connector": "EC-6A", "side": "R"}
      ]
    },
    {
      "name": "SPK 1.01 HL ARRAY 1",
      "tag": "SPK 1.01 HL ARRAY 1",
      "make": "Meyer Sound",
      "model": "TIGRA-L",
      "column": 1,
      "align_to": {"device": "SWTCH 4.01 HL UPPER", "socket": "LAN 1", "my_socket": "LAN_IN 1"},
      "sockets": [
        {"name": "LAN_IN 1", "type": "IN", "signal": "LAN", "connector": "EC-6A", "side": "L"}
      ]
    }
  ],
  "circuits": [
    {
      "from": {"device": "SWTCH 4.01 HL UPPER", "socket": "LAN 1"},
      "to":   {"device": "SPK 1.01 HL ARRAY 1", "socket": "LAN_IN 1"},
      "signal": "MILAN PRI"
    }
  ]
}
```

### Devices

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | **Unique.** ConnectCAD links objects by name string, so a duplicate is rejected. |
| `tag` | no | Display Tag. Defaults to `name`. |
| `make`, `model` | no | If they match a device symbol already in the drawing, that symbol is stamped out instead of a new block being drawn — better, because somebody already laid it out correctly. |
| `sockets` | yes* | \*Unless a symbol matches, or the make/model is in ConnectCAD's device database. Order matters: sockets stack down their edge in the order listed. |
| `column` | no | Horizontal position, 0 upwards. Signal flows left to right, so sources are column 0. |
| `row` | no | Vertical position, 0 downwards. Coarse — for separating unrelated chains. |
| `align_to` | no | Sets the vertical position precisely. See below. |
| `section` | no | Which band of the drawing this block belongs in. See **Sections**. |
| `id` | no | Unique handle for this block. Defaults to `name`; **required** when a device appears in more than one section. Circuits reference this. |
| `x`, `y` | no | Explicit drawing units, overriding `column`/`row`. Rarely what you want. |

**If you know the real make and model, give them and omit `sockets`.** CC Tools
ships with ConnectCAD's device database — 2,734 devices with their actual
connector sets — and will use it. A Shure ULXD4Q gets the sockets Shure gave
it, which is better than any guess.

The catch: you then don't know the socket names, so you can't write circuits
against them. Do one or the other per device — either give `sockets` yourself
and reference those names in circuits, or give only make/model and leave that
device unwired for the user to connect. Don't guess names for a device you
didn't list sockets for.

### Sockets

| Key | Meaning |
|---|---|
| `name` | e.g. `LAN 1`, `LAN_IN 1`, `OUT 3`. Referenced by circuits, so spell it identically there. |
| `type` | `IN`, `OUT`, or `IO`. |
| `signal` | e.g. `LAN`, `AES`, `ANALOG`. |
| `connector` | e.g. `EC-6A`, `XLR3F`. |
| `side` | `L` or `R`. Inputs conventionally `L`, outputs `R`. |

### Circuits

`from` and `to` each name a `device` — by its **id** — and a `socket`, both of
which must exist in the device list.

| Key | Meaning |
|---|---|
| `signal` | The circuit's own signal, e.g. `MILAN PRI`. **Not** the same as the sockets' signal: a real drawing joins two `LAN` sockets with a `MILAN PRI` circuit. Real values in use: `LINE`, `PWR`, `MILAN PRI`, `MILAN SEC`, `MIDC`, `AES`, `OPT`, `DANTE`, `LAN`. |
| `cable` | A short human-readable name for the run, drawn along the middle of the line. Write one for every circuit — this is a design decision, and it is the label a person reads off the drawing. Keep it short enough to sit on a line. |

Do **not** set a wire number. ConnectCAD numbers wires itself, by signal type,
and a second scheme fighting it makes a mess.

## Sections

These drawings divide **one** design layer into horizontal bands by signal
type and location — analog in one band, power in another, speakers in another —
and sheet viewports crop each band onto its own drawing.

Give each device a `section`. Put the sections in the order you want them down
the page:

```json
"sections": [{"name": "Analog — Stage"}, {"name": "Power — Stage"}],
"devices": [ ... ]
```

Two rules follow from bands being separate regions:

**A circuit may not cross sections.** It could never be wired, because the two
ends are nowhere near each other. The job will be rejected.

**A device that belongs in two sections is drawn twice** — once per section —
and each copy needs its own `id`. Keep the `name` identical; that is what makes
them the same ConnectCAD device. This is the normal case: a speaker appears in
the speaker section carrying its network feed, and again in the power section
carrying its mains.

```json
{"id": "spk1-net",   "name": "SPK 1.01 HL ARRAY 1", "section": "Network", ...},
{"id": "spk1-power", "name": "SPK 1.01 HL ARRAY 1", "section": "Power",   ...}
```

Then a circuit says `{"device": "spk1-power", "socket": "AC IN"}` — unambiguous,
where the bare name would not have been.

---

## The one rule that decides whether it works

**ConnectCAD only wires two sockets that sit at the same height.** Wiring is not
a property of the circuit list — the circuit list says what *should* connect,
and the geometry is what actually connects it. Two devices whose sockets are a
quarter inch out of line produce a schematic with no circuits in it.

Sockets hang from the top of a device on a fixed pitch: the first is two grid
units below the top, then one grid unit each after that, counted separately
down the left and right edges.

**So: for every circuit, give the destination device an `align_to`.**

```json
"align_to": {"device": "<the other device>", "socket": "<its socket>", "my_socket": "<my socket>"}
```

That says "put me at whatever height makes my socket line up with theirs". The
plug-in computes the y using the same pitch it draws with, so the two cannot
drift apart. Never work the offsets out yourself — you would have to know the
drawing's grid size, and you don't.

Alignment chains: if speaker 2 aligns to the switch, speaker 3 can align to
speaker 2. Something in each chain must be positioned by `column`/`row` alone,
or there is no fixed point to measure from. Alignment works **within** a
section only — bands are stacked afterwards, so aligning across them is
meaningless and is reported as an error.

**A device can only be aligned once.** If a device is fed from two different
sources, you can only line up one of those circuits. Align the one that matters
most, and tell the user in your reply which circuits will need dragging into
place by hand — that is far more useful than silently drawing a schematic where
half the wiring is missing.

## Conventions worth following

- **Uppercase names.** House style, and CC Tools normalises to it anyway.
- **`name` and `tag` identical** unless there is a reason to differ.
- **Names carry position**, e.g. `SPK 1.01 HL ARRAY 1` — type, number, location.
- **Signal flows left to right.** Sources at column 0, sinks at the far right.
- **Reuse the drawing's own vocabulary.** If the user attaches a document
  profile exported from their drawing, match its makes, models, signal names
  and connector types exactly rather than inventing near-misses. A signal named
  `MILAN PRI` in one place and `Milan Primary` in another is two signals.

## Before you send it

Check each of these, because each one produces a silently wrong drawing:

- [ ] Every device `id` is unique. Repeated `name`s are fine and expected;
      repeated ids are not.
- [ ] Every circuit references devices by **id**, not by name.
- [ ] No circuit crosses a section boundary.
- [ ] Every `socket` named in a circuit exists on that device, spelled the same.
- [ ] Every circuit's destination has an `align_to` back to its source (or you
      have told the user which ones you could not align).
- [ ] Every circuit has a `cable` name.
- [ ] The JSON parses.
- [ ] It is offered as a **downloadable file**, not a code block.
