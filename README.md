# CC Tools

A ConnectCAD naming utility for **Vectorworks 2026** — one Python menu command that tidies device names and display tags without breaking the links between objects.

ConnectCAD ties most of its objects together **by name string**. Rename a schematic Device and its rack Equipment Item, panel layouts, panel connectors and circuit endpoints can quietly stop pointing at it. These tools do the renaming *and* carry every reference along with it.

## What it does

Running **CC Tools** opens a launcher where you tick one or more tools. They always run in the order below.

| Tool | What it does |
|---|---|
| **Dump Fields** | Read-only diagnostic. Inventories every ConnectCAD record, finds every field holding a device name, flags stray whitespace, and probes which ConnectCAD scripting routines your setup exposes. |
| **Normalise Names** | UPPERCASE and/or trim names and display tags, keeping all linked objects in sync. |
| **Match Names and Display Tags** | Finds objects whose Name and Display Tag disagree and lets you choose which one wins — in bulk, or one at a time. |

Normalise runs before Match on purpose: uppercasing and trimming collapses every case-only and whitespace-only mismatch (`amp1` vs `AMP1`), so Match only asks about pairs that genuinely differ.

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

Normalise has a **Preview only** checkbox that reports what would change without touching the drawing.

## Before you trust it on real work

The logic is covered by a test suite that runs the plug-in against a mock Vectorworks API — 77 targeted cases plus 2,500 randomised documents checking that links never silently break. But the suite cannot exercise Vectorworks itself, so a few behaviours remain unverified against a live document: undo granularity, whether circuits re-derive their cached names after a reset, and whether socket edits survive a parent reset.

**Work on a copy of your drawing until you've seen a preview report you agree with.**

## More detail

[`DESIGN.md`](DESIGN.md) covers how ConnectCAD's linking actually works, why the tools are built the way they are, and what has and hasn't been verified — including some findings from disassembling the ConnectCAD plug-in that aren't documented anywhere else.
