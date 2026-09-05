# CC Tools

A ConnectCAD naming utility for **Vectorworks 2026** — one Python menu command that tidies device names and display tags without breaking the links between objects.

ConnectCAD ties most of its objects together **by name string**. Rename a schematic Device and its rack Equipment Item, panel layouts, panel connectors and circuit endpoints can quietly stop pointing at it. These tools do the renaming *and* carry every reference along with it.

## What it does

Running **CC Tools** opens a launcher where you tick one or more tools. Nothing is ticked by default — these edit a live drawing, so choosing is deliberate. Ticked tools always run in the order below.

| Tool | What it does |
|---|---|
| **Dump Fields** | Read-only diagnostic. Inventories every ConnectCAD record, finds every field holding a device name, flags stray whitespace, and probes which ConnectCAD scripting routines your setup exposes. |
| **Normalise Names** | UPPERCASE and/or trim names and display tags, keeping all linked objects in sync. |
| **Match Names and Display Tags** | Finds objects whose Name and Display Tag disagree and lets you choose which one wins — in bulk, or one at a time. |
| **Spell Check** | Finds likely typos in free-text fields, and doubles as a reviewable find-and-replace across every ConnectCAD object. |
| **Export Reference Schematic** | Read-only. Writes a signal-flow layer out as JSON — devices, their sockets, and the real circuit wiring — for use as a worked example. |

Normalise runs before Match on purpose: uppercasing and trimming collapses every case-only and whitespace-only mismatch (`amp1` vs `AMP1`), so Match only asks about pairs that genuinely differ. Spell Check runs last, once every name has settled.

### Spell Check, and why it isn't just a dictionary

The vocabulary in a ConnectCAD drawing is `SWTCH`, `AVB Pri`, `EC-6A`, `pCON grey`, `NE8FDX-P6-B`. A dictionary would reject nearly all of it, so suspects are found from the drawing itself: a term used on one or two objects that is a single edit away from one used on many is probably a typo (`Cirrcuit` against `Circuit`). A system word list, where present, is used only to *spare* real words from suspicion — never to condemn a term for not being English.

But frequency only tells you what is **consistent**, not what is **correct** — a mistake used everywhere looks exactly like house style. So the default action shows you **every term in the drawing** in a scrollable table with its usage counts: pick a row, type a replacement, press Set. Nothing leaves Vectorworks. Rarest terms sort to the top, so anything odd is near the front rather than buried.

Multi-word entries are replaced literally, which makes this a find-and-replace across ConnectCAD objects — the piece Vectorworks' own Find and Replace doesn't cover. The same list can also be exported to CSV and re-applied if you'd rather do bulk work in a spreadsheet.

Every replacement is a **global token substitution**, not a per-object edit. Fixing a typo fixes it identically in the device, its tag, its equipment item and every reference at once — which is what keeps name-linked objects linked through the change.

**Only free-text fields are touched:** names, display tags, user fields, and circuit labels. Dropdown values (connector, signal, cable type), library values (make, model, description), endpoint caches and room/rack references are all left alone — those are chosen from lists, not typed, so a "correction" there would just be a value the library rejects.

Reports are written to `~/Documents/CC Tools/` under timestamped filenames, so runs never overwrite each other.

## Install

1. In Vectorworks: **Tools ▸ Plug-ins ▸ Plug-in Manager…**
2. **New… ▸ Command**, name it `CC Tools`, set language to **Python**.
3. **Edit Script…**, paste the entire contents of [`cc_tools.py`](cc_tools.py), then save.
   Include the final `run_cc_tools()` line — that call is what actually runs the command.
4. Add it to your workspace: **Tools ▸ Workspaces ▸ Edit Current Workspace ▸ Menus**, and drag **CC Tools** into a menu.

No dependencies, no files to install alongside it. The whole plug-in is that one script.

## Using it

Run **Dump Fields** first on any new drawing. It changes nothing, and its report tells you whether the field names and ConnectCAD routines this build expects are actually present.

Both mutating tools default to **Selected objects only**, so nothing happens document-wide unless you ask. Linked partners are still resolved across the whole document either way, so a selection-scoped run never leaves an equipment item holding a stale name.

Match defaults to **Export list only**, which writes a CSV of every mismatch and changes nothing. Look at that before choosing a real action:

- **Set Display Tag = Name** — link-safe; tags are labels nothing points at.
- **Set Name = Display Tag** — renames the device and resyncs every reference to it.
- **Review one at a time** — decide per device.

Normalise and Spell Check both have a **Preview only** checkbox that reports what would change without touching the drawing.

Spell Check keeps an ignore list at `~/Documents/CC Tools/spelling_ignore.txt`. Answering *Ignore always* adds a term to it, so a house abbreviation is only ever asked about once. Delete a line to start flagging it again.

## Status: alpha

This works and has been used on real drawings, but it is early software that edits your document directly. Keep a backup, and use **Preview only** or **Export list only** the first time you point a tool at an unfamiliar file.

## More detail

[`DESIGN.md`](DESIGN.md) covers how ConnectCAD's linking actually works, why the tools are built the way they are, and what has and hasn't been verified — including some findings from disassembling the ConnectCAD plug-in that aren't documented anywhere else.
