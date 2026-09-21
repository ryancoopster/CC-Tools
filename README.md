# CC Tools

A ConnectCAD toolkit for **Vectorworks 2026** — one Python menu command that builds, searches and edits ConnectCAD drawings while keeping the links between objects pointing where they should.

It does three kinds of work:

- **Draws schematics.** Describe the system to Claude and hand it `JOB-SPEC.md`; it writes a job file. The plug-in reads that file and builds the devices, their connectors, the wiring between them and the sections they sit in.
- **Finds what nothing else can.** Vectorworks' own Find and Replace cannot see inside plug-in object records, which is where a ConnectCAD drawing keeps everything worth finding. Search walks every field of every ConnectCAD object; Find and Replace changes them in bulk, with every proposed edit shown before anything is written.
- **Keeps the links intact.** ConnectCAD ties most of its objects together **by name string**. Rename a schematic Device and its rack Equipment Item, panel layouts, panel connectors and circuit endpoints can quietly stop pointing at it. Every tool here does the renaming *and* carries the references it knows about along with it.

## What it does

Running **CC Tools** opens a launcher where you tick one or more tools. Nothing is ticked by default — these edit a live drawing, so choosing is deliberate. Ticked tools always run in the order below, whichever order you tick them in.

The launcher is split in two: the tools used while drafting, and the ones used when setting a drawing up or working out why something went wrong.

| Tool | What it does |
|---|---|
| **Dump Fields** | Read-only diagnostic. Inventories every ConnectCAD record, finds every field holding a device name, flags stray whitespace, and probes which ConnectCAD scripting routines your setup exposes. |
| **Normalise Names** | UPPERCASE and/or trim names and display tags, keeping all linked objects in sync. |
| **Match Names and Display Tags** | Finds objects whose Name and Display Tag disagree and lets you choose which one wins — in bulk, or one at a time. |
| **Spell Check** | Finds likely typos in free-text fields, and doubles as a reviewable find-and-replace across every ConnectCAD object. |
| **Search ConnectCAD Objects** | Read-only. Searches **every field** of every ConnectCAD object — the ones Vectorworks' own Find and Replace cannot see. Selects the matches in the drawing. |
| **Find and Replace** | Replaces text in device and socket names and tags, and circuit labels, numbers and cable names. Shows every proposed change in a table to tick before anything is written. |
| **Reconcile Panel Connectors** | Finds sockets renamed since the last run — including renames typed straight into the OIP — and brings the panel connectors pointing at them up to date. |
| **Draw schematic job** | Opens a file dialog, then builds the devices and wiring from the job file Claude gave you. Falls back to ConnectCAD's device database for a device's real connectors. |
| **Preferences** | Column spacing, row spacing, gap between sections, circuit line mode, device label symbol. |
| **Export prompt for Claude** | Read-only. Writes a profile of how this drawing is built, to hand Claude so new work matches it. |
| **Export Reference Schematic** | Read-only. Writes a signal-flow layer out as JSON — devices, their positions and sockets, and the real circuit wiring — for use as a worked example. |
| **Creation Probe** | Diagnostic that **writes**. Builds a handful of throwaway devices and circuits to prove what this install's ConnectCAD actually lets a script do. Run it on a scratch file, never on real work. |

Normalise runs before Match on purpose: uppercasing and trimming collapses every case-only and whitespace-only mismatch (`amp1` vs `AMP1`), so Match only asks about pairs that genuinely differ. Spell Check runs last, once every name has settled. Preferences run first, so ticking them alongside **Draw schematic job** draws with the settings you just saved.

Preferences are kept in `~/Documents/CC Tools/preferences.json`, which you can edit directly. Spacing is in printed inches and is scaled by the layer, so a job drawn on a 1:2 layer keeps its proportions.

### Search, and what Find and Replace can't reach

Vectorworks' Find and Replace does not look inside plug-in object records, which
is where a ConnectCAD drawing keeps everything worth finding: cable names,
signals, makes and models, endpoint caches, room and rack references. Search
walks every field of every ConnectCAD object instead.

It is read-only — it finds and selects, never edits. That separation is
deliberate: it means Search can safely cover fields that would be dangerous to
rewrite, like the endpoint caches and dropdown values Spell Check leaves alone.

Two options earn their keep on real drawings:

- **Match the whole field** compares the entire value rather than looking
  inside it. With an empty search box it lists every *blank* field — which is
  how you find a circuit whose destination was never set.
- **Include internal fields** exposes ConnectCAD's own bookkeeping
  (`__ISNEW`, control points). Hidden by default, because there are hundreds of
  them and they bury everything else.

A search for a value with a trailing space finds the sort of thing nothing else
will: names link by exact string, so `SPK 3.04 US FILL HR LOWER ` and
`SPK 3.04 US FILL HR LOWER` are two different devices, and on screen they look
identical.

Results go to a timestamped CSV whether or not you select them.

### Find and Replace

Search finds; this changes. It offers only the fields that are free text *and*
identify the object: device and socket names and tags, and a circuit's Label,
Number and Cable. Dropdown values, endpoint caches and library fields are never
touched — a "correction" in a dropdown is a value ConnectCAD rejects, and an
endpoint cache is rewritten on the next reset anyway.

Scope is the usual three — selection, layer, whole document — with tick boxes
per object type and an option to match the whole string rather than part of it.
Whole-string is what lets you rename `SPK 1.01` without also hitting
`SPK 1.010`.

**No replacement is written until you have seen it listed.** Running the search produces a
table of every proposed change — type, field, the current text and the text
after replacing — with each row ticked. Untick what you don't want, press
Replace, and it happens with no further prompts.

The one that matters: **a device name is a link key.** Renaming a device has to
rename its equipment item and every panel reference too, or they come apart.
That is on by default and can be turned off, which is occasionally what you
want and usually not. Those follow-on edits aren't listed in the table because
they aren't choices — they're what keeps the rename from breaking the drawing.

### Reconcile Panel Connectors

ConnectCAD does not push a schematic socket rename out to the panel connectors
that point at it. Rename a socket in the Object Info palette and the panel goes
on showing the old name, with no warning. Rename it with **Find and Replace**
and CC Tools carries the references along — but a rename typed straight into
the OIP happens where no tool can see it.

**This cannot be a background service.** There is no timer, no idle handler, no
document-level event hook and no modeless dialog in the VectorScript API;
observing another vendor's plug-in object needs the C++ SDK, which is how
ConnectCAD itself is built. A menu command runs once and exits.

So it works by snapshot and diff. Every plug-in object carries a persistent
uuid, so CC Tools records each socket's uuid and name, and on the next run a
uuid whose name has changed is a rename — known from the uuid, not guessed from
the names themselves. The panel connectors pointing at the old name are then
brought up to date, shown in the same review table as Find and Replace.

The snapshot records the last **reconciled** state, not the last observed one,
and that distinction matters: it is refreshed at the end of every CC Tools run,
but a socket whose name has drifted from its record is a rename nobody has
dealt with yet, so its entry is left alone. Rename a socket, run Normalise or
Spell Check or anything else half a dozen times, reconcile next week — the
rename is still there waiting. Advancing the record on an unrelated run would
erase the only evidence it happened.

A rename is only settled once **every** reference to the old name has been
updated. Untick one row and the rename stays on the books, so a later run can
finish it.

The first run on a drawing has nothing to compare against and says so.

Worth binding to a keyboard shortcut if you rename in the OIP often: it is one
command and does nothing when there is nothing to do.

### Spell Check, and why it isn't just a dictionary

The vocabulary in a ConnectCAD drawing is `SWTCH`, `AVB Pri`, `EC-6A`, `pCON grey`, `NE8FDX-P6-B`. A dictionary would reject nearly all of it, so suspects are found from the drawing itself: a term used on one or two objects that is a single edit away from one used on many is probably a typo (`Cirrcuit` against `Circuit`). A system word list, where present, is used only to *spare* real words from suspicion — never to condemn a term for not being English.

But frequency only tells you what is **consistent**, not what is **correct** — a mistake used everywhere looks exactly like house style. So the default action shows you **every term in the drawing** in a scrollable table with its usage counts: pick a row, type a replacement, press Set. Nothing leaves Vectorworks. Rarest terms sort to the top, so anything odd is near the front rather than buried.

Multi-word entries are replaced literally, which makes this a find-and-replace across ConnectCAD objects — the piece Vectorworks' own Find and Replace doesn't cover. The same list can also be exported to CSV and re-applied if you'd rather do bulk work in a spreadsheet.

Every replacement is a **global token substitution**, not a per-object edit. Fixing a typo fixes it identically in the device, its tag, its equipment item and every reference it can reach at once — which is what keeps name-linked objects linked through the change.

**Only free-text fields are touched:** names, display tags, user fields, and circuit labels. Dropdown values (connector, signal, cable type), library values (make, model, description), endpoint caches and room/rack references are all left alone — those are chosen from lists, not typed, so a "correction" there would just be a value the library rejects.

Reports are written to `~/Documents/CC Tools/` under timestamped filenames, so runs never overwrite each other.

## Before you run it

**CC Tools is beta software, and it edits your open drawing directly.**

**Save your file before every run, and keep backups you can go back to.** Not
just once before the first run — before each one. A single run can rename
hundreds of objects across a document, or draw a whole schematic, and there is
no guarantee you can take that back: the plug-in does not group its work into
one undo event, so how much a single Undo reverses is up to Vectorworks and the
Plug-in Manager's settings, and has not been established. Assume you cannot rely
on Undo to rescue a run you did not want.

The safer first move on any unfamiliar drawing is to look before you write.
**Dump Fields** changes nothing and reports what this drawing and this
ConnectCAD build actually contain. **Normalise** and **Spell Check** have a
**Preview only** box, **Match** defaults to **Export list only**, and **Search**
never writes at all.

This has been used on real drawings and it is covered by a large test suite, but
it is not a finished product and it is not warranted. It is offered as is, with
no guarantee that it is fit for any particular purpose. **The authors accept no
responsibility for lost work, damaged files or any other loss arising from its
use.** If a drawing matters, back it up before pointing this at it.

## Install

Paste one short script. It downloads the rest itself.

1. In Vectorworks: **Tools ▸ Plug-ins ▸ Plug-in Manager…**
2. **New… ▸ Command**, name it `CC Tools`, set language to **Python**.
3. **Edit Script…**, click in the empty box, paste the whole of
   [`tools/stub.py`](tools/stub.py) — GitHub has a copy button at the top right
   of the file — then **OK**, and **OK** again to close the Plug-in Manager.
   If it asks about restarting, **Continue Without Restart** is fine.
4. **Tools ▸ Workspaces ▸ Edit Current Workspace ▸ Menus**, find **CC Tools** in
   the list on the left, and drag it into a menu on the right. **OK**.
   *If it isn't in that list, restart Vectorworks and try this step again.*
5. Pick **CC Tools** from that menu. It will offer to download itself — say yes.

That is the whole install — five steps and about twenty clicks, once. There is
no terminal, no download to unzip, and nothing to drag into a system folder.

Step 4 is the one that cannot be automated, and the reason is worth knowing: a
plug-in has to be in a menu before anything can run it, so it can never put
itself there.

What step 5 does: it fetches `cc_tools.py` and `JOB-SPEC.md` from this
repository into `~/Documents/CC Tools/`, checks the program against the
checksum published with it, and starts. From then on CC Tools updates itself
and the Plug-in Manager is never needed again.

### Why a loader and not the whole program

Vectorworks cannot reload a plug-in's code in a running session. There is no
API for it — `ReloadPlugin`, `RegisterPlugin`, `SetPluginScript` and six other
spellings return nothing across the application binary and all 128 of its
library bundles — and its own Plug-in Manager says installing a plug-in needs
a restart.

So if the program lived inside the plug-in, every update would mean quitting
Vectorworks. Keeping it in a plain file means an update is one file replaced,
effective the next time you pick **CC Tools** from the menu.

The loader also pastes in a few seconds. The program is 8,000 lines.

### If something goes wrong

- **It says it cannot reach GitHub.** You are offline, or a firewall is in the
  way. Nothing was installed and nothing is broken; try again later, or copy
  `cc_tools.py` into `~/Documents/CC Tools/app/` by hand and it will start.
- **It says the download does not match its checksum.** It refused to install
  something it could not verify. That is the tool working correctly, not a
  fault — tell Ryan.
- **It starts but says it fell back to the previous version.** An update left
  a bad file. It is running the copy it kept; delete
  `~/Documents/CC Tools/app/cc_tools.py` and run it again for a fresh one.

### Updating

The first run asks whether CC Tools may check GitHub for new versions, and how
often. Nothing reaches the network until you answer, and **Never** means never.

When there is a new version you get the release notes and three choices:
**Update now**, **Skip this version**, or **Ask me later**. There is also a
**Check for updates** button at the bottom of the launcher, which ignores both
the interval and anything you skipped.

**Installing an update closes CC Tools.** The new code is on disk, but
Vectorworks is still holding the old one in memory and nothing can reload it —
so carrying on would run the version you just replaced. Pick CC Tools from the
menu again and you are on the new one.

Downloads are verified before they are installed — byte count, SHA-256, and
whether the file compiles — and the version being replaced is kept alongside
as `cc_tools.py.previous`. Both settings live in **Preferences**, which also
shows when the last check ran and why it failed if it did.

An update refreshes `JOB-SPEC.md` too, so everyone stays on the same device
list — but **only if you have not edited it**. If you have, it is left exactly
as it is and the update says so.

## Using it

Run **Dump Fields** first on any new drawing. It changes nothing, and its report tells you whether the field names and ConnectCAD routines this build expects are actually present.

Both mutating tools default to **Selected objects only**, so nothing happens document-wide unless you ask. Linked partners are still resolved across the whole document either way, so a selection-scoped run should not leave an equipment item holding a stale name.

Match defaults to **Export list only**, which writes a CSV of every mismatch and changes nothing. Look at that before choosing a real action:

- **Set Display Tag = Name** — link-safe; tags are labels nothing points at.
- **Set Name = Display Tag** — renames the device and resyncs every reference to it.
- **Review one at a time** — decide per device.

Normalise and Spell Check both have a **Preview only** checkbox that reports what would change without touching the drawing.

Spell Check keeps an ignore list at `~/Documents/CC Tools/spelling_ignore.txt`. Answering *Ignore always* adds a term to it, so a house abbreviation is only ever asked about once. Delete a line to start flagging it again.

## Designing a schematic with Claude

CC Tools can draw a schematic that Claude designs — no API key, developer
account or terminal needed:

1. In the CC Tools launcher, click **Copy JOB-SPEC.md for Claude**, and paste
   into a Claude conversation — one file, spec and device list. That button is
   the recommended route: it copies the same file the plug-in reads, and keeps
   itself current.
2. Describe what you want.
3. Download the `.json` file Claude gives you.
4. **CC Tools ▸ Draw schematic job**, and pick that file.

[SCHEMATIC-JOBS.md](SCHEMATIC-JOBS.md) covers it properly, including how to make
the result match a drawing you already have.

## More detail

[`DESIGN.md`](DESIGN.md) covers how ConnectCAD's linking actually works, why the tools are built the way they are, and what has and hasn't been verified — including some findings from disassembling the ConnectCAD plug-in that aren't documented anywhere else.
