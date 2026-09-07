# Designing a schematic with Claude

CC Tools can draw a schematic that Claude designed. No API key, no developer
account, no terminal — you talk to Claude the way you normally do, and it hands
back a file.

## The flow

1. **Give Claude [`JOB-SPEC.md`](JOB-SPEC.md).** Drag it into a new Claude
   conversation (claude.ai or the desktop app). That one file teaches it the
   format and the rules, and carries the device list — the real connectors of
   the devices you use, so it does not invent any. Do this once per
   conversation.
2. **Describe what you want.** Plain English. *"A Luminex 10i-IP feeding four
   Meyer TIGRA-L arrays over Milan primary, one array per output."* Go back and
   forth until the design is right — this is the part worth spending time on.
3. **Download the file it gives you.** Claude replies with a `.json` file.
   Save it anywhere; Downloads is fine.
4. **In Vectorworks: CC Tools ▸ Draw schematic job.** A file dialog opens.
   Pick the file you just downloaded. It draws.

Undo works normally if the result isn't what you wanted.

## The curated device list

The device list lives at the end of [`JOB-SPEC.md`](JOB-SPEC.md) — the same
file you hand Claude. Claude writes circuits against the socket names in it,
and puts those sockets in the job, so the plug-in builds exactly what Claude
designed. That is the normal path and it needs no setup.

**Optionally**, drop a copy of the file in `~/Documents/CC Tools/` (as
`devices.md` or under its own name). The plug-in reads the device list out of
it and ignores the spec prose. This only matters for a job that names a device
*without* listing its sockets — then your curated entry is used instead of
ConnectCAD's shipped database. Nothing breaks if you skip it.

It ships seeded from the Geffen Hall drawing — 37 devices, 23 of them carrying
measured dimensions, weights and rack heights from the rack layout. Add to it
whenever a schematic needs a device it does not cover; that is the moment a
model would otherwise guess.

CC Tools falls back to ConnectCAD's own database of 2,734 devices for anything
not in the file. Stock manufacturer symbol libraries are deliberately not
searched: on a normal install almost all of them are undownloaded placeholders,
and the ones that do arrive are inconsistent with each other.

## Matching an existing drawing

If you want the new work to match a drawing you already have — its makes,
models, signal names, connector types — run **CC Tools ▸ Export prompt for
Claude** first. It writes `~/Documents/CC Tools/schematic_prompt.txt`, a profile
of how that document is built, including a worked example taken from its own
wiring. Attach that alongside `JOB-SPEC.md` at step 1.

Without it Claude will still produce a valid drawing; it just won't know your
house vocabulary.

## Sections

These drawings divide **one** design layer into horizontal bands by signal type
and location — analog in one band, power in another, speakers in another — with
sheet viewports cropping each band onto its own drawing. Jobs describe that
directly: every device names a `section`, and the bands are stacked down the
layer in the order the job lists them, separated by the gap set in
**Preferences**.

Two things follow from bands being separate regions of the drawing, and the
tool checks both rather than drawing something that cannot work:

- **A circuit cannot cross sections.** Its two ends would be nowhere near each
  other, so it could never wire.
- **A device that belongs in two sections is drawn twice.** A speaker appears
  in the speaker section carrying its network feed, and again in the power
  section carrying its mains. Both blocks keep the same **name** — that is what
  makes them the same ConnectCAD device — and each gets its own `id`, so a
  circuit can say which one it means.

That second point is why device names legitimately repeat in a job, and why
circuits reference ids rather than names.

### Sections and classes do different jobs

ConnectCAD files every circuit in a class named after its signal —
`CC-Circuit-Signal-LINE`, `CC-Circuit-Signal-PWR`, and so on — and a sheet
viewport filtered to one of those is that signal's drawing. CC Tools sets that
class on every circuit it creates, because ConnectCAD's own automatic classing
has already run and closed by the time a script writes the signal.

**Devices are never classed**, by ConnectCAD or by this tool. That is correct
and deliberate: a device belongs on every sheet its circuits appear on.

So the two mechanisms are not alternatives. Classes divide the **signals**;
sections divide the **drawing area**, which is why a device is drawn again in
each section — each region needs its own block to attach its own circuits to.

## Cable names

Each circuit carries a `cable` — the short human-readable name drawn along the
middle of the line. Claude writes one per circuit; it is a design decision, not
something derivable, and it is the label a person actually reads off the sheet.

Wire **numbers** are left alone. ConnectCAD numbers wires itself, by signal
type, and a second scheme fighting it would only make a mess.

## Layout is wiring

The thing to understand, because it explains most surprises:

**ConnectCAD connects sockets that line up horizontally.** The circuit list in
the job says what *should* connect. Where the devices sit is what actually
connects them. A device a quarter inch too high draws fine and wires to
nothing.

`JOB-SPEC.md` handles this with `align_to`, which lets Claude say "line my input
up with that output" and leaves the arithmetic to the plug-in. You shouldn't
have to think about it — but when a circuit comes back **NOT WIRED**, this is
almost always why.

One consequence worth knowing: a device fed from two different sources can only
be lined up with one of them. Claude should tell you when that happens. The
second circuit is drawn as a device that needs nudging, not a failure.

## Reading the report

Every run writes a timestamped report to `~/Documents/CC Tools/`. It records:

- the layer, its scale, the drawing units and the grid the sizing came from
- each device: `symbol` if a matching device symbol was stamped out, `built` if
  it was drawn from scratch
- how many circuits actually wired

That last number is **read back from the drawing**, not counted from the job.
`ConnectSelected` returning cleanly proves nothing, so the tool goes and looks.
Anything listed as `NOT WIRED` genuinely isn't.

## Troubleshooting

| What you see | Why |
|---|---|
| "Cannot draw the job" with a list | The JSON is malformed or inconsistent. Paste the list back to Claude — it's written to be handed straight over. |
| Devices drawn, 0 circuits wired | Nothing lined up. Check the job has `align_to` on its destination devices. |
| Some circuits not wired | Usually a device fed from two sources — only one alignment can win. Nudge the others by hand. |
| `no symbol and no sockets listed` | A device with neither a matching symbol nor a socket list. Ask Claude to add sockets. |
| Devices are the wrong size | The active layer's scale. Everything is drawn on the active layer, sized to that layer — check the report's first few lines. |
| `CC_DeviceFromShape is unavailable` | No ConnectCAD licence in this session. |

## If you'd rather not copy files around

Claude Desktop can be given filesystem access via MCP, which lets it write the
job file straight into `~/Documents/CC Tools/`. That removes the download step
and nothing else — the plug-in works the same way, and its file dialog opens in
that folder. It is a convenience, not a different feature, and it needs a
config file edit that most people won't want to make. The download route above
is the supported one.
