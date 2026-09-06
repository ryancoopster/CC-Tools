# Designing a schematic with Claude

CC Tools can draw a schematic that Claude designs. You do not need an API key,
a developer account, or anything installed beyond the plug-in — the handoff is
two files in a folder.

## The short version

1. In Vectorworks, run **CC Tools ▸ Export prompt for Claude**
2. Open `~/Documents/CC Tools/schematic_prompt.txt`, type what you want at the
   bottom, and copy the whole file
3. Paste it into Claude and talk about the design until you are happy with it
4. Save Claude's final JSON reply as `~/Documents/CC Tools/schematic_job.json`
5. Back in Vectorworks, run **CC Tools ▸ Draw schematic job**

Everything is reviewable before anything is drawn: the prompt is a text file you
can read and edit, and the job is a JSON file you can inspect, hand-edit, keep,
or re-run.

## Which Claude?

**The chat app** — [claude.ai](https://claude.ai) or the Claude desktop app.
That is what this is designed around, and it is the right shape for the work:
you are having a design conversation, not writing code. You can attach a PDF of
an existing drawing, disagree with a proposal, and ask for changes before
anything reaches Vectorworks.

Claude Code works too, but it is a terminal tool aimed at programmers. There is
no advantage here.

**Any plan works, including free.** The prompt is text and the reply is text.

## What the prompt contains

`Export prompt for Claude` reads the open drawing and writes:

- **How this drawing is built** — the make/model pairs in use and the socket set
  each one carries, the shapes device names take, the signals, connectors, rooms,
  racks and layers in play. Claude follows your conventions because they are
  measured from your drawing, not described to it.
- **Device symbols available** — devices that can be reproduced exactly.
- **A worked example** — real devices and wiring from your drawing, in the same
  format the reply must take. An example in the output format teaches far more
  than instructions about the format.
- **The job format** and the rules that matter.

Nothing leaves your machine except what you paste.

## The job format

```json
{
  "devices": [
    {
      "name": "SWTCH 4.01 HL UPPER",
      "tag": "SWTCH 4.01 HL UPPER",
      "make": "Luminex",
      "model": "10i-IP",
      "column": 0,
      "row": 0,
      "sockets": [
        {"name": "LAN 1", "type": "OUT", "signal": "LAN",
         "connector": "EC-6A", "side": "R"}
      ]
    }
  ],
  "circuits": [
    {"from": {"device": "SWTCH 4.01 HL UPPER", "socket": "LAN 6"},
     "to":   {"device": "SPK 1.01 HL ARRAY 1", "socket": "LAN_IN 1"},
     "signal": "MILAN PRI"}
  ]
}
```

- **`name` is the link key.** ConnectCAD ties devices to equipment items, panel
  layouts and circuit endpoints by name string, so names must be unique unless
  you deliberately mean the same physical device drawn twice.
- **`column` and `row`** place devices on a grid, left to right along the signal
  path. Explicit `x` and `y` override them.
- **`sockets` are ignored when a device symbol matches** the make and model — the
  symbol is reproduced exactly instead, sockets and all.
- **`side`** is `L` or `R`, the edge the socket sits on.

## Layout is wiring

ConnectCAD connects sockets by **horizontal alignment**, so where devices sit
decides what can be joined. Put sources in lower columns than destinations, and
devices that talk to each other at compatible heights. A schematic that looks
right generally wires right; one that does not, will not.

`Draw schematic job` reports every circuit it could not make rather than
pretending success, and it verifies each one by reading the connection back
from ConnectCAD — a wiring command that runs without error has not necessarily
wired anything.

## If something goes wrong

- **"Not valid JSON"** — the reply probably has commentary around it. Keep only
  the `{ ... }`. A ```` ```json ```` fence is stripped automatically.
- **"…is not in the device list"** — a circuit names a device that was never
  defined. Fix it in the file or let it draw the rest.
- **Circuits not wired** — usually device positions: the two sockets are not
  aligned. Move the devices, or adjust `column`/`row` and re-run.
- **Devices look wrong** — run **Dump Fields** first. Its report says whether
  ConnectCAD's routines are available and what the drawing's grid is.

Undo reverses a run. Work on a copy until you have seen a result you like.

## Doing it without the copy-paste

If you are comfortable configuring MCP, point the filesystem server at
`~/Documents/CC Tools/` and Claude can read the prompt and write the job itself.
That needs Node.js and an edit to `claude_desktop_config.json`, which is why it
is not the documented default — the copy-paste route needs nothing at all.

The job format is identical either way.
