# ConnectCAD schematic job — spec and device list

**Give Claude this one file.** It contains everything needed: how to write a
job file that the CC Tools plug-in can draw in Vectorworks, and the curated
list of devices with their real connectors and physical properties.

Then describe the schematic you want, and Claude replies with a `.json` file
to download.

That is the whole flow: **this file goes to Claude, the `.json` Claude gives
back goes to the plug-in.**

**Also drop a copy of this file in `~/Documents/CC Tools/`.** The plug-in reads
the device list out of it and ignores the rest. Sockets do not need it — the
job carries those — but **dimensions, weight, power and rack height do**, since
the job does not carry them. Without the copy, a device gets its physical data
only if ConnectCAD's own database happens to know it, which for most real
equipment it does not.

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

### Where socket lists should come from

**Never invent connectors.** In order of preference:

1. **The device list at the end of this file** — if the device is in it, use
   exactly the socket names it gives. The plug-in reads the same list, so your
   circuits and its sockets will match by construction. This is the best case
   and the one to aim for.
2. **Look the device up properly** if it is not in that file — the
   manufacturer's real connector set — and say clearly in your reply that you
   did, and what you found. Suggest the user add it to the device list so the
   next schematic comes out the same. Include the whole entry for them to
   paste:
   the socket table AND the physical properties, which are

   ```
   - Width: 482.6 mm
   - Height: 44.45 mm
   - Depth: 262.89 mm
   - Weight: 3.84 kg
   - Power: 30 W
   - Rack mounted: yes
   - Rack U: 1
   ```

   Always write the unit. Rack U is the device's **size** in rack units, not
   where it sits in a rack. **Leave out anything you could not find** — a
   blank line is a job someone can finish, a plausible number is a wrong
   answer nobody will catch.
3. **Give only make and model, and omit `sockets`.** CC Tools falls back to
   ConnectCAD's shipped database of 2,734 devices. The catch: you then do not
   know the socket names, so you cannot write circuits against them — leave
   that device unwired and say so.

What you must not do is guess socket names for a device you did not look up.
A wrong name draws a schematic that wires nothing, and it looks fine until
somebody checks.

### Show the unused sockets too

A device block carries **every socket it has of that section's signal type** —
connected or not. An eight-output switch shows eight outputs on the network
drawing even if only five are used; a speaker shows both its analog inputs even
if one is spare. Spare capacity is information, and a drawing that hides it
cannot be read for what is left.

Split them by section, the same way the device is: the analog drawing shows
that device's unused mic and line connections, the network drawing shows its
unused network ports. A socket only ever appears on the drawing for its own
signal.

### Which side a socket goes on

`side` is about the **drawing**, not the socket's electrical nature. Signal
flows left to right, so:

- On the device a circuit comes **from**, that socket is on the **right**.
- On the device a circuit goes **to**, that socket is on the **left**.

This catches people out with switches and other `IO` sockets. A switch port
feeding a speaker is `"side": "R"` on the switch — but the *same kind of port*
on a switch that is **receiving** an uplink is `"side": "L"` on that block.
Getting this wrong is not cosmetic: two sockets both on the right cannot be
joined, and the circuit silently does not wire.

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
| `signal` | The circuit's own signal, e.g. `MILAN PRI`. **Not** the same as the sockets' signal: a real drawing joins two `LAN` sockets with a `MILAN PRI` circuit. Use only signals ConnectCAD knows — `LINE`, `PWR`, `LAN`, `AES`, `DANTE`, `OPT` are standard, and `MILAN PRI`, `MILAN SEC`, `MIDC` are defined in this user's own library. Inventing one makes ConnectCAD flag every circuit carrying it. |
| `cable` | A short human-readable name for the run, drawn along the middle of the line. **Ask the user whether they want cable names before writing any**, and if they do, write one for **every** circuit — a drawing where some lines are labelled and others are not looks like an oversight. |

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

### Choose sections by SIGNAL TYPE, and nothing finer

One section per signal type — network, analog, power. **Not** one per subgroup.
"Network — Main L", "Network — Main R" and "Network — Subs" should be a single
"Network" section: they carry the same signal and belong on the same drawing.

This matters because of the rule below. Splitting a section splits every device
that spans it, and a switch broken into three blocks because its outputs were
filed under three headings is worse than no sections at all. A device should
appear **once per signal type**, never more.

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

### One device fanning out to many needs a column each

This is the trap, and it is arithmetic rather than judgement. Sockets are one
grid unit apart. A device is at least **three** grid units tall. So if a switch
feeds eight speakers and you align each to the next socket down **while leaving
them all in one column**, consecutive speakers sit one unit apart while being
three units tall — they overlap, every time, and ConnectCAD cannot route to a
socket buried under another device.

**Give each one its own column**, stepping right as you step down:

```
speaker 1  column 1   aligned to LAN 1
speaker 2  column 2   aligned to LAN 2
speaker 3  column 3   aligned to LAN 3
```

A daisy-chain already does this naturally — each device in the next column —
which is why chains work and fan-outs do not. The plug-in now refuses a job
whose devices would overlap, so getting this wrong costs a round trip.

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

## Show a preview first

**Before you hand over the `.json`, draw the schematic as an HTML artifact and
let the user look at it.** Then wait for them to say go before producing the
file.

This is not decoration. The preview's job is to make the one failure that is
otherwise invisible visible: **a circuit whose two ends are not at the same
height cannot be wired**, and on a preview it shows up immediately as a sloped
line. Everything else about a bad job you can see in the JSON; that one you
cannot.

### Draw it to the plug-in's own geometry

Work in grid units, `G`. One grid unit is a quarter inch in a typical drawing,
so `G = 16` pixels gives a readable preview.

| Thing | Where it goes |
|---|---|
| Device top edge | `y` from `align_to`, or `-row × 10G` |
| Device left edge | `column × 16G`, centred on that |
| Device width | `12G` |
| Device height | `(2 + most sockets on either side) × G` |
| Socket *i* on an edge | `deviceTop − (2 + i) × G`, numbered per edge from 0 |
| Section | stacked below the previous one, flush |

Left-side sockets sit on the left edge, right-side on the right. A circuit is a
line from one socket to the other.

### What the preview has to show

- Every device as a labelled block, with its name and its sockets
- Every circuit as a line between the two sockets it names, **drawn where those
  sockets actually are** — never straightened, never nudged to look right
- The cable name along the middle of each line
- Section bands, labelled
- **Any sloped line called out explicitly**, in red or similar, with a note
  saying which circuit it is and that it will not wire

If every line is horizontal, the job is sound. If one slopes, fix the
`align_to` and show the preview again — do not hand over a file you already
know draws a schematic that wires nothing.

Keep it plain: boxes, lines, labels. It is a check, not a rendering.

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
- [ ] A preview was shown and every circuit line came out horizontal.
- [ ] No two devices in the same section share a column unless they are far
      enough apart not to overlap — a fan-out needs a column each.
- [ ] Every signal is one ConnectCAD defines.
- [ ] Sections are by signal type only, and no device is split more finely.
- [ ] Every block shows its unused sockets for that section's signal.
- [ ] Every circuit leaves a right-hand socket and arrives at a left-hand one.
- [ ] Cable names were asked about, and are either on every circuit or none.
- [ ] It is offered as a **downloadable file**, not a code block.

---

## The device list

Seeded from the Geffen Hall drawing. Whitespace has been normalised — a few
socket names there carried double or trailing spaces, which are invisible on
screen and break the name match.

**Physical properties are filled in only where ConnectCAD's own database had
them — 2 of the 28.** The rest are left blank on purpose rather than filled
with plausible numbers. Fill them in as you look each device up; that is what
this file is for.

### Align Array | AL3

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN | IN | LAN | EC-6A | L |

### Custom | Connector Panel

- Width: 18.92 in
- Height: 7 in
- Depth: 3.15 in
- Rack mounted: yes
- Rack U: 4

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| 1-49 | IN | LINE | --- | L |
| 1-49 | OUT | LINE | XLR3F | R |

### Focusrite | REDNET-D16R AES

- Width: 19.06 in
- Height: 1.75 in
- Depth: 10.35 in
- Weight: 3.84 kg
- Power: 30 W
- Rack mounted: yes

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| DANTE 1 | IO | LAN | RJ45 | R |
| DANTE 2 | IO | LAN | RJ45 | R |
| WD_CLK _N | IN | WC | BNC | L |
| WD_CLK_OUT | OUT | WC | BNC | R |
| AES_IN | IN | AES | XLR3M | L |
| AES_OUT | OUT | AES | XLR3F | R |
| SPDIF_IN | IN | AES | RCA | L |
| SPDIF_OUT | OUT | AES | RCA | R |
| AES_IN&OUT 1-8 | IO | AES | DB25M | R |
| AES_IN&OUT 9-16 | IO | AES | DB25M | R |

### Luminex | 10I 10G 2X SFP 1G x8

- Width: 9.5 in
- Height: 1.75 in
- Depth: 13 in
- Weight: 3.4 kg
- Power: 30 W
- Rack mounted: yes
- Rack U: 1

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |
| LAN 3 | IO | LAN | RJ45 | R |
| LAN 4 | IO | LAN | RJ45 | R |
| LAN 5 | IO | LAN | RJ45 | R |
| LAN 6 | IO | LAN | RJ45 | R |
| LAN 7 | IO | LAN | RJ45 | R |
| LAN 8 | IO | LAN | RJ45 | R |
| SFP 9 | IO | OPT | LC | R |
| SMP 10 | IO | LAN | DUO-SMF | R |

### Luminex | 10T-IP

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN 8 | IO | LAN | EC-6A | R |
| LAN 6 | IO | LAN | EC-6A | R |
| LAN 5 | IO | LAN | EC-6A | R |
| LAN 4 | IO | LAN | EC-6A | R |
| LAN 3 | IO | LAN | EC-6A | R |
| LAN 2 | IO | LAN | EC-6A | R |
| LAN 7 | IO | LAN | EC-6A | R |
| LAN 1 | IO | LAN | EC-6A | R |

### Luminex | 16I 10G

- Width: 9.49 in
- Height: 1.76 in
- Depth: 11.67 in
- Weight: 2.4 kg
- Power: 25 W
- Rack mounted: yes

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |
| LAN 3 | IO | LAN | RJ45 | R |
| LAN 4 | IO | LAN | RJ45 | R |
| LAN 5 | IO | LAN | RJ45 | R |
| LAN 6 | IO | LAN | RJ45 | R |
| LAN 7 | IO | LAN | RJ45 | R |
| LAN 8 | IO | LAN | RJ45 | R |
| LAN 9 | IO | LAN | RJ45 | R |
| LAN 10 | IO | LAN | RJ45 | R |
| LAN 11 | IO | LAN | RJ45 | R |
| LAN 12 | IO | LAN | RJ45 | R |
| SFP 13 | IO | OPT | DUO-SMF | R |
| SFP 14 | IO | OPT | DUO-SMF | R |
| SFP 15 | IO | OPT | DUO-SMF | R |
| SFP 16 | IO | OPT | DUO-SMF | R |

### Luminex | 30i 10G POE

- Width: 18.98 in
- Height: 1.75 in
- Depth: 12.2 in
- Rack mounted: yes
- Rack U: 1

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |
| LAN 3 | IO | LAN | RJ45 | R |
| LAN 4 | IO | LAN | RJ45 | R |
| LAN 5 | IO | LAN | RJ45 | R |
| LAN 6 | IO | LAN | RJ45 | R |
| LAN 7 | IO | LAN | RJ45 | R |
| LAN 8 | IO | LAN | RJ45 | R |
| LAN 9 | IO | LAN | RJ45 | R |
| LAN 10 | IO | LAN | RJ45 | R |
| LAN 11 | IO | LAN | RJ45 | R |
| LAN 12 | IO | LAN | RJ45 | R |
| LAN 13 | IO | LAN | RJ45 | R |
| LAN 14 | IO | LAN | RJ45 | R |
| LAN 15 | IO | LAN | RJ45 | R |
| LAN 16 | IO | LAN | RJ45 | R |
| LAN 17 | IO | LAN | RJ45 | R |
| LAN 18 | IO | LAN | RJ45 | R |
| LAN 19 | IO | LAN | RJ45 | R |
| LAN 20 | IO | LAN | RJ45 | R |
| LAN 21 | IO | LAN | RJ45 | R |
| LAN 22 | IO | LAN | RJ45 | R |
| LAN 23 | IO | LAN | RJ45 | R |
| LAN 24 | IO | LAN | RJ45 | R |
| SFP 25 | IO | OPT | LC | R |
| SFP 26 | IO | LAN | SFP | R |
| SFP 27 | IO | LAN | SFP | R |
| SFP 28 | IO | LAN | SFP | R |
| SFP 29 | IO | LAN | SFP | R |
| SFP 30 | IO | LAN | SFP | R |

### Meyer Sound | 2100-LFC

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3F | R |
| LAN | IN | LAN | EC-6A | L |

### Meyer Sound | Galaxy 408

- Width: 19 in
- Height: 1.75 in
- Depth: 16.14 in
- Weight: 6 kg
- Power: 26.33 W
- Rack mounted: yes
- Rack U: 1

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| AES_IN A/B | IN | LINE | XLR3M | L |
| LINE_IN B | IN | LINE | XLR3M | L |
| AES_IN C/D | IN | LINE | XLR3M | L |
| LINE_IN D | IN | LINE | XLR3M | L |
| L Sub Top OUT 1 | OUT | LINE | XLR3F | R |
| L Sub Middle OUT 2 | OUT | LINE | XLR3F | R |
| L SUb Bottom OUT 3 | OUT | LINE | XLR3F | R |
| R Sub Top OUT 4 | OUT | LINE | XLR3F | R |
| R Sub Middle OUT 5 | OUT | LINE | XLR3F | R |
| R Sun Bottom OUT 6 | OUT | LINE | XLR3F | R |
| LINE_ OUT 7 | OUT | LINE | XLR3F | R |
| LINE_ OUT 8 | OUT | LINE | XLR3F | R |
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |

### Meyer Sound | Galaxy 816

- Width: 19 in
- Height: 3.47 in
- Depth: 16.14 in
- Weight: 7.6 kg
- Rack mounted: yes

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| AES_IN A/B | IN | AES | XLR3M | L |
| LINE_IN B | IN | LINE | XLR3M | L |
| AES_IN C/D | IN | AES | XLR3M | L |
| LINE_IN D | IN | LINE | XLR3M | L |
| AES_IN E/F | IN | AES | XLR3M | L |
| LINE_IN F | IN | LINE | XLR3M | L |
| AES_IN G/H | IN | AES | XLR3M | L |
| LINE_IN H | IN | LINE | XLR3M | L |
| LINE_OUT 1 | OUT | LINE | XLR3F | R |
| LINE_OUT 2 | OUT | LINE | XLR3F | R |
| LINE_OUT 3 | OUT | LINE | XLR3F | R |
| LINE_OUT 4 | OUT | LINE | XLR3F | R |
| LINE_OUT 5 | OUT | LINE | XLR3F | R |
| LINE_OUT 6 | OUT | LINE | XLR3F | R |
| LINE_OUT 7 | OUT | LINE | XLR3F | R |
| LINE_OUT 8 | OUT | LINE | XLR3F | R |
| LINE_OUT 9 | OUT | LINE | XLR3F | R |
| LINE_OUT 10 | OUT | LINE | XLR3F | R |
| LINE_OUT 11 | OUT | LINE | XLR3F | R |
| LINE_OUT 12 | OUT | LINE | XLR3F | R |
| LINE_OUT 13 | OUT | LINE | XLR3F | R |
| LINE_OUT 14 | OUT | LINE | XLR3F | R |
| LINE_OUT 15 | OUT | LINE | XLR3F | R |
| LINE_OUT 16 | OUT | LINE | XLR3F | R |
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |

### Meyer Sound | MPS-488X

- Width: 18.92 in
- Height: 1.76 in
- Depth: 15.31 in
- Weight: 6.9 kg
- Power: 1350 W
- Rack mounted: no

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN 1 | IN | LINE | XLR3M | L |
| LINE_IN 2 | IN | LINE | XLR3M | L |
| LINE_IN 3 | IN | LINE | XLR3M | L |
| LINE_IN 4 | IN | LINE | XLR3M | L |
| LINE_IN 5 | IN | LINE | XLR3M | L |
| LINE_IN 6 | IN | LINE | XLR3M | L |
| LINE_IN 7 | IN | LINE | XLR3M | L |
| LINE_IN 8 | IN | LINE | XLR3M | L |
| MIDC_OUT 1 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 2 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 3 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 4 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 5 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 6 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 7 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 8 | OUT | MIDC | TBLK-5 | R |
| LAN | IO | LAN | RJ45 | R |

### Meyer Sound | TIGRA-L

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN 1 | IN | LAN | EC-6A | L |
| LAN_IN 2 | IN | LAN | EC-6A | L |
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3F | R |

### Meyer Sound | TIGRA-W

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| Power In | IN | PWR | powerCON TRUE 1 F | L |
| Power Thru | OUT | PWR | powerCon TRUE1 M | R |

### Meyer Sound | ULTRA-X22

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3M | R |

### Meyer Sound | ULTRA-X40

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3M | R |

### Meyer Sound | ULTRA-X42

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3M | R |

### Meyer Sound | UP-4slim

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| MIDC_IN | IN | MIDC | TBLK-5 | L |

### Middle Atlantic | EB1

- Width: 18.92 in
- Height: 1.75 in
- Depth: 0.12 in
- Rack mounted: yes
- Rack U: 1

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| ? | IO | MILAN PRI | EC-6A | R |
| ? | IO | MILAN SEC | EC-6A | R |
| ? | IO | CTL | EC-6A | R |
| ? | IO | MILAN PRI | EC-6A | R |
| ? | IO | MILAN SEC | EC-6A | R |

### Middle Atlantic | UPS-S1000R

- Width: 19.06 in
- Height: 1.75 in
- Depth: 15.31 in
- Weight: 16.3 kg
- Rack mounted: yes
- Rack U: 1

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| PWR_IN | IN | PWR | NEMA 5-15P | L |
| PWR_OUT 1 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 2 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 3 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 4 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 5 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 6 | OUT | PWR | NEMA 5-15P | R |

### Radial | POWER-2

- Width: 18.92 in
- Height: 1.75 in
- Depth: 10.05 in
- Rack mounted: yes
- Rack U: 1

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| PWR_IN | IN | PWR | NEMA 5-15P | L |
| PWR_OUT 1 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 2 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 3 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 4 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 5 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 6 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 7 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 8 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT Front | OUT | PWR | NEMA 5-15R | R |

### SAI | DB25 to AES XLR B/O

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| AES_I/O | IN | AES | Built In | L |
| AES_IN 1-2 | IN | AES | Built In | L |
| AES_IN 1-2 | IN | AES | Built In | L |
| AES_IN 3-4 | IN | AES | Built In | L |
| AES_IN 3-4 | IN | AES | Built In | L |
| AES_OUT 1-2 | OUT | AES | Built In | R |
| AES_OUT 3-4 | OUT | AES | Built In | R |
| AES_OUT 5-6 | OUT | AES | Built In | R |
| AES_OUT 7-8 | OUT | AES | Built In | R |

### SAI | Powercon "Y"

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| ? | IN | PWR | pCON-W | L |
| ? | OUT | PWR | pCON-B | R |
| ? | OUT | PWR | pCON-B | R |

### Ubiquiti | Cloud Gateway Ultra

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| WAN | IO | LAN | RJ45 | R |
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |
| LAN 3 | IO | LAN | RJ45 | R |
| LAN 4 | IO | LAN | RJ45 | R |

### Ubiquiti | U6 Mesh

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN | IO | LAN | RJ45 | R |

### theatrixx | 5-L21-30 distro

- Width: 18.92 in
- Height: 21 in
- Depth: 22 in
- Rack mounted: yes
- Rack U: 12

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| L21-30_IN 1 | IN | PWR | L21/30 F | L |
| L21-30_IN 2 | IN | PWR | L21/30 F | L |
| L21-30_IN 3 | IN | PWR | L21/30 F | L |
| L21-30_IN 4 | IN | PWR | L21/30 F | L |
| L21-30_IN 5 | IN | PWR | L21/30 F | L |
| 20A 208v_OUT 1 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 2 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 3 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 4 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 5 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 6 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 7 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 9 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 10 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 11 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 12 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 120v_OUT 13 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 14 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 15 | OUT | PWR | pCON grey | R |
| 20A 208v_OUT 8 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 120v_OUT 16 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 17 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 18 | OUT | PWR | pCON grey | R |

### theatrixx | DGH 21-30 breakout

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| L21-30_IN | IN | PWR | L21/30 F | L |
| 20A 208v_OUT 1 | OUT | PWR | powerCon TRUE1 M | R |
| 20A 208v_OUT 2 | OUT | PWR | powerCon TRUE1 M | R |
| 20A 120v_OUT 1 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 2 | OUT | PWR | NEMA 5-20R | R |

### theatrixx | L21-30 PD

- Width: 18.92 in
- Height: 3.5 in
- Depth: 9.26 in
- Rack mounted: yes
- Rack U: 2

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| L21-30_IN | IN | PWR | L21/30 F | L |
| 20A 120v_OUT 1A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 1B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 2A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 2B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 3A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 3B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 4A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 4B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 5A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 5B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 6A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 6B | OUT | PWR | NEMA L5-20P | R |

### theatrixx | PB-11

- Width: 19 in
- Height: 1.75 in
- Depth: 9 in
- Rack mounted: yes
- Rack U: 1

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| PWR_IN | IN | PWR | pCON blue | L |
| PWR_OUT 1 | OUT | PWR | pCON | R |
| PWR_OUT 2 | OUT | PWR | pCON | R |
| PWR_OUT 1 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 2 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 3 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 4 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 5 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 6 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 7 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 8 | OUT | PWR | NEMA 5-15P | R |

## Known from the rack layout only

Physical properties measured from the drawing. **No socket lists
yet** — add them as these devices come up in a schematic.

### Ampetronic | C-5 Loop Driver

- Width: 18.92 in
- Height: 1.75 in
- Depth: 7.48 in
- Rack mounted: yes
- Rack U: 1

### Audio Accessories | WEP_961_SH

- Width: 18.92 in
- Height: 1.75 in
- Depth: 4 in
- Rack mounted: yes
- Rack U: 1

### Custom Panel | Custom Patch Panel

- Width: 18.92 in
- Height: 21 in
- Depth: 4 in
- Rack mounted: yes
- Rack U: 12

### Middle Atlantic | BR1

- Width: 18.92 in
- Height: 1.75 in
- Depth: 0.99 in
- Rack mounted: yes
- Rack U: 1

### Middle Atlantic | UPS-S1500R

- Width: 19.01 in
- Height: 3.51 in
- Depth: 16.5 in
- Weight: 24.5 kg
- Rack mounted: yes

### Yamaha | DSP-RX-EX

- Width: 18.92 in
- Height: 8.75 in
- Depth: 19.3 in
- Rack mounted: yes
- Rack U: 5

### Yamaha | RPIO 222

- Width: 18.92 in
- Height: 8.75 in
- Depth: 19.3 in
- Rack mounted: yes
- Rack U: 5

### Yamaha | Rio1608

- Width: 18.92 in
- Height: 5.25 in
- Depth: 12 in
- Weight: 9.6 kg
- Rack mounted: yes

### Yamaha | TF-Rack

- Width: 18.92 in
- Height: 5.25 in
- Depth: 16.12 in
- Weight: 9.2 kg
- Power: 85 W
- Rack mounted: yes
- Rack U: 3
