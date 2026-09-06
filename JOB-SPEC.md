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
| `sockets` | yes* | \*Unless a symbol matches. Order matters: sockets stack down their edge in the order listed. |
| `column` | no | Horizontal position, 0 upwards. Signal flows left to right, so sources are column 0. |
| `row` | no | Vertical position, 0 downwards. Coarse — for separating unrelated chains. |
| `align_to` | no | Sets the vertical position precisely. See below. |
| `x`, `y` | no | Explicit drawing units, overriding `column`/`row`. Rarely what you want. |

### Sockets

| Key | Meaning |
|---|---|
| `name` | e.g. `LAN 1`, `LAN_IN 1`, `OUT 3`. Referenced by circuits, so spell it identically there. |
| `type` | `IN`, `OUT`, or `IO`. |
| `signal` | e.g. `LAN`, `AES`, `ANALOG`. |
| `connector` | e.g. `EC-6A`, `XLR3F`. |
| `side` | `L` or `R`. Inputs conventionally `L`, outputs `R`. |

### Circuits

`from` and `to` each name a `device` and a `socket`, both of which must exist in
the device list. `signal` is the circuit label, e.g. `MILAN PRI`.

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
or there is no fixed point to measure from.

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

- [ ] Every device `name` is unique.
- [ ] Every `socket` named in a circuit exists on that device, spelled the same.
- [ ] Every circuit's destination has an `align_to` back to its source (or you
      have told the user which ones you could not align).
- [ ] The JSON parses.
- [ ] It is offered as a **downloadable file**, not a code block.
