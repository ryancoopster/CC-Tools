# CC Tools — design notes

How ConnectCAD actually behaves, why these tools are built the way they are, and
what has and hasn't been verified. For what the plug-in does and how to install
it, see the [README](README.md).

Findings here come from dumping real jobs, from disassembling the ConnectCAD
plug-in binary, and from probes run in a live drawing. Most of it is not
documented publicly. **Where something is inferred rather than observed, it says
so** — several confident-sounding claims in earlier versions of this file turned
out to be wrong, and the ones that cost the most time were the ones stated
without a source.

**One plug-in**, `cc_tools.py`, installed as a single menu command named
**CC Tools**. Running it opens a launcher where you tick one or more tools,
which always run in a fixed order whatever order you tick them.

| | Tool | |
|---|---|---|
| *drafting* | Normalise Names | uppercase / trim, links updated with the name |
| | Match Names and Display Tags | reconcile Name vs Display Tag |
| | Spell Check | typos and reviewable find-and-replace |
| | Search ConnectCAD Objects | read-only, every field |
| | Find and Replace | writes, with a review table |
| | Reconcile Panel Connectors | after renaming in the OIP |
| | Draw schematic job | build a schematic from JSON |
| *setup* | Preferences | spacing, line mode, label symbol |
| | Export prompt for Claude | document profile |
| | Dump Fields | read-only diagnostic |
| | Export Reference Schematic | read-only, drawing as JSON |
| | Creation Probe | writes — run it on a scratch file |
| *launcher* | Copy JOB-SPEC.md | puts the spec on the clipboard |
| | Check for updates | ignores the interval and any skip |

All output goes to `~/Documents/CC Tools/` under timestamped filenames.

### Why one file

Vectorworks creates one `.vsm` per menu command — there is no multi-command
plug-in. Shipping these as separate commands would duplicate the whole engine
(record readers, document walk, `classify`, link planning, collision checks) so
every fix had to land many times and the copies would drift. The launcher keeps
one plug-in with one copy of the engine.

Cost: one extra click, and no per-tool keyboard shortcuts.

### Run order is fixed

Reconcile → Search → Dump → Preferences → Replace → Normalise → Match → Spell →
Reference → Probe → Prompt → Job.

The order encodes dependencies. Reconcile first, so later tools read references
that are current. Preferences before Draw job, so a job is drawn with settings
just saved. Normalise before Match, because uppercasing and trimming collapses
every case-only and whitespace-only mismatch (`amp1` vs `AMP1`), leaving Match
to ask only about pairs that genuinely differ. Spell Check last, once every name
has settled.

**A tool that stops halts the chain** — a collision, an unresolved field, an
error mid-write — and the summary says what never ran. Merely *cancelling* a
dialog is different: the chain continues.

---

## The constraint everything is built around

Most ConnectCAD links are **by name string**. Rename one side and the others
silently unlink. The diagnostic's reference scan found these:

| Holder | Field | Points at |
|---|---|---|
| `EquipItem` | `name` | Device name |
| `PanelLayout` | `DeviceName` | Device **name or tag** |
| `PanelConnector` | `ConnectedDev` | Device **name or tag** |
| `PanelConnector` | `ConnectedSkt` | the socket it is **wired to** |
| `PanelConnector` | `SocketName` | the socket it **represents** |
| `PanelConnector` | `DisplayTag` | label; mirrors `SocketName` until customised |
| `Circuit` | `Src/Dst_Dev_Name`, `_Skt_Name`, `_Dev_Tag` | caches, refreshed on reset |

**A PanelConnector names its socket twice**, and the two are not
interchangeable. A real drawing was found carrying the name in `SocketName` and
`DisplayTag` with `ConnectedSkt` *empty*, so a sync that followed only
`ConnectedSkt` left every panel connector pointing at a name that no longer
existed — silently, because the field it checked was blank and matched nothing.

**A device tag is a reference target too.** `ConnectedDev` holds either the name
or the tag, so tag edits carry a sync of their own. Names are consulted first: a
value that *is* a device name means that device, whatever else it may
coincidentally equal.

### Except Device ↔ Equipment, which is a stored reference

`CC_GetEquipmentItem(hDevice)` resolves a **persisted association** — a ref
number in tagged data — with no string comparison anywhere. Names are only the
bootstrap key ConnectCAD uses to *form* the link.

Inferring that link from name equality is wrong where it hurts: with two devices
named `SWTCH 4.01` only one is truly associated, but name matching claims both.
The sync asks ConnectCAD instead, and falls back to name matching only when the
routine is unavailable — saying so in the report rather than guessing quietly.

### Renaming is not a field write

**`CC_OnFindAndReplace` is the supported rename**, the same code path as typing
in the OIP Name field. A plain `SetRField` writes the string and leaves the
stored association pointing at whatever it used to match, so a device renamed by
script kept a link the interface would have broken and never gained the one it
should have.

The two sides behave **differently**, which is why order matters:

- **Device** → `UpdateDeviceLocation`. *Severs* a stale association and clears
  location data. It contains no association call at all — it only breaks.
- **EquipItem** → `OnEquipNameChange` → `FindAndUpdateDevices`. The only routine
  that *forms* the link: looks devices up by the equipment's **new** name,
  associates one, copies room, rack and rack-U across.

So **devices are renamed before equipment**. An earlier version had it the other
way round, on the assumption that the device side re-formed the link; the pair
was disassociated and never put back together.

The routine is a silent no-op without a ConnectCAD licence, so the value is read
back rather than assumed, a plain write is the fallback, and every report says
how many renames fell back and what that means for their links.

**It also mirrors the Display Tag** onto the new name whenever tag equals name —
the usual case. Where the user asked for that it is recorded as an applied edit;
where they deliberately left the tag row unticked, it is put back.

---

## Sentinels

`<DEVICE>`, `<EXT>`, `<SOCKET>` and `---` are placeholders, not names.
`is_unnamed()` treats them and the empty string identically everywhere: link
maps, sync matching and collision counting all refuse them. In one real file
**101 of 203 devices** sit at `<DEVICE>` — that is 101 blanks, not a
duplicate-name collision, and renaming the sentinel would give every one of them
the same name.

**`Device-External` is not a device, but it is not nothing.** Its `name` really
is always `<EXT>` and must never be renamed. But its **tag** carries the off-page
endpoint label — `To SWTCH 2.01 2nd Floor Pri` — which is free text someone
typed. `classify()` returned `None` for it, which hid it from Search, Spell Check
and Find and Replace alike, so a rename pass updated every Device, Socket,
EquipItem and PanelConnector and left these reading the old name. It now has its
own kind with the tag editable and the sentinel still untouchable.

---

## How wiring actually works

Read out of `ConnectSelected_EventSink::ConnectDevices`, and confirmed by a
probe in a live drawing.

**Sockets do not need to be at the same height.** The function contains no
floating-point comparison at all. A probe wired three circuits offset by 0.10",
0.85" and 1.60"; ConnectCAD drew each with a clean elbow. An `align_to`
mechanism and a staircase layout were built on the opposite belief, inherited
from an early note and never tested — the staircase made every fan-out circuit
graze the device in the previous column and drawings four times wider than
needed.

**The real gate is X.** Selected devices are grouped into columns by
`DoBoundsIntersectOnX`, which compares bounding boxes with `<=` — touching edges
count as one column. If the whole selection resolves to **one** column, wiring is
skipped and an interactive tool is silently activated instead: nothing drawn,
nothing reported. The draw path checks for this before starting.

**Pairing is positional.** Within a column, devices sort by bounding-box centre Y
descending and sockets likewise; the Nth source socket takes the Nth still-free
destination. **Socket names in a job are never consulted.** So the order a job
lists a device's circuits in, and the order its targets are stacked, decide which
socket each circuit lands on — get it wrong and every circuit is still made, onto
the wrong sockets, which is harder to notice than a missing one.

Source sockets must be orientation `R`; destinations must not be. `side` is
therefore graphical, not electrical: the same IO port is `R` where it feeds and
`L` where it receives.

### Circuits

`CircuitType` has exactly four values, lowercase: `polyline` (ConnectCAD's
default), `rounded`, `chamfer`, `arrow` — bounded by a four-entry jump table.
Two values offered by an earlier build, `direct` and `orthogonal`, do not exist;
they were invented from plausibility. **Do not write a ConnectCAD enum value you
have not read out of the binary or a real drawing.**

The first three share one computed route polygon and differ only in corner
rendering. `arrow` is a structurally different object — paired stubs linked by
`__Arrow_ID` — so it is never offered as a line mode and never written over an
existing routed circuit.

Setting the field alone does nothing; the value is consumed in the reset handler,
so `ResetObject` is required and sufficient.

**Circuits are auto-classed** `CC-Circuit-Signal-<SIGNAL>`, but only once, gated
on a hidden `__Version` parameter. `ConnectSelected` creates *and* resets the
circuit, so by the time a script writes a signal that gate has closed and the
class is wrong — the tool sets it explicitly, after the reset. Devices are never
auto-classed.

**Elbows all turn at the same distance by default**, so a fan-out into a stacked
column draws its vertical runs on top of one another. Real drawings stagger
`ControlPoint03X` per circuit; the tool does the same. *Inferred* from two
samples — consistent with them and with nothing else obvious, but not confirmed
against the binary.

---

## Where device data comes from

In order: a **device symbol** in the open document (someone drew it, sockets
placed); the **sockets a job lists**; the **curated list** at the end of
`JOB-SPEC.md`; ConnectCAD's **shipped database**.

Stock manufacturer symbol libraries are deliberately *not* searched. Of 346 in
`Libraries/ConnectCAD/Device/`, **345 are 10-byte `.vwx.proxy` placeholders**
fetched on demand; exactly one had been downloaded. A tool that searched them
would find one manufacturer.

The shipped database is `ConnectCAD Devices DB.txt` — 24 tab-separated columns,
**2,735 device blocks over 17,127 lines**, no header row, CRLF, UTF-8 with BOM.
Read it as bytes: text mode mangles it. A device owns a block of rows; each row
is a socket *series* whose quantity expands with the number appended **verbatim**
to the prefix — 481 rows carry a deliberate trailing space (`MIC ` → `MIC 1`)
while 16,646 do not (`HDV_OUT` → `HDV_OUT1`).

Seventeen blocks collide once make and model are normalised: the same product
entered twice under two spellings. They are merged, keeping whichever entry
expands to more sockets — taking the later one, as an earlier build did, gave
the BSS Blu50, the JBL Nano Patch+ and a Teranex Mini a short connector list. It also uses `LOOP` and `IOloop`
where `Socket.type` takes only `IN`/`OUT`/`IO`; both are bidirectional and map to
`IO`.

`SignalTypes.txt` defines the signal vocabulary. Ten of its 80 rows are **category
headings** marked with `=`, not signals. The user's own copy uses bare CR line
endings where the application copy uses CRLF — splitting on CRLF alone reads it
as empty and makes every custom signal look invented.

---

## Updating itself

**A plug-in's code cannot be reloaded in a running session.** `ReloadPlugin`,
`RefreshPlugin`, `RegisterPlugin`, `SetPluginScript`, `RebuildPlugin`,
`ReloadScripts` and `VSRefresh` return **zero hits** across the 205MB
application binary and all 128 library bundles. Of the 16 core routines with
"Plugin" in the name — and one more, `vsoGetPluginStyleSym`, in the library
list — all concern plug-in *styles*, localization or the running instance. Vectorworks' own Plug-in Manager agrees — *"Installing new
plug-ins require restart of Vectorworks"* — and there is no routine to quit or
relaunch the application either.

So the pasted plug-in is a **loader stub** (`tools/stub.py`) and this file is a
**payload** it reads and `exec()`s. An update replaces one plain `.py` and takes
effect on the next menu click.

The stub also **bootstraps the install**: on a first run with no payload it
offers to fetch this file and `JOB-SPEC.md` from the repository, so the whole
install is one paste. That is deliberately done from inside Vectorworks rather
than by a downloadable installer — Vectorworks is already an app the user has
approved, so it sidesteps Gatekeeper, the quarantine flag on anything
downloaded, and macOS's privacy protection on `~/Documents`, each of which
would otherwise put a dialog in front of a non-technical drafter.

The cost is that the stub carries its own copy of the TLS and verification
logic, which can drift from this file's. `t38_stub.py` pins them together: the
repository, branch, CA bundle list and the `CC_TOOLS_PAYLOAD` contract are all
asserted equal across the two files, so drift fails the suite rather than
shipping. The alternative was shipping a prebuilt `.vsm`, which is **more viable than it
sounds**: the container is fully portable. Every non-zero header byte is
accounted for and none is machine-specific — no paths, usernames, serials,
licence ids, UUIDs or timestamps — the 3,225-byte trailer is byte-identical
across plug-ins and holds only zero padding and four copies of a generic icon,
and there is no checksum. The only constraint found is a major-version stamp at
**offset 134** (uint16 LE): 13 on VW2023, 14 on VW2025, 16 on VW2026.

It was still not taken, because it does not remove a step that matters. It
needs Vectorworks closed while the file is copied — the application holds the
pasted script in memory and was observed rewriting `CC Tools.vsm` mid-session —
and it needs a restart afterwards, since plug-ins are enumerated at startup. So
it trades "paste a short script" for "quit, install, relaunch", and adds a
binary artefact to the repository that has to be rebuilt by hand. Worth
revisiting only if the paste step turns out to be the thing people get wrong.

The workspace menu step could also be automated, but **not** by editing the
`.vww` XML: the workspace is plain XML and names items by `UniversalName`, but
each carries a `ResourceManagerID` that is assigned at runtime and is not
stable, so a hand-written entry can bind to the wrong command. Vectorworks'
own `ws*` routines are the supported route. It is left manual anyway, because
a plug-in cannot run to fix the workspace until it is already in the
workspace.

**`vs.InstallCertificate()` must never be called.** Vectorworks' own shipped
uploaders (`ExportWebGl`, `OBJExporter`) call it, and the bootstrap embedded in
the main binary shows what it does: when `PYTHONHTTPSVERIFY` is unset it sets
`ssl._create_default_https_context = ssl._create_unverified_context`. **It makes
HTTPS work by turning certificate verification OFF.** For a file that is
downloaded and then executed, that is the whole attack.

An explicit CA bundle is not optional either way: the bundled OpenSSL's
compiled-in `OPENSSLDIR` is `/Library/Frameworks/Python.framework/…`, which does
not exist in this install, and `ssl.py` has no macOS keychain fallback — so a
default context loads **zero** roots and every request dies with
`CERTIFICATE_VERIFY_FAILED`. `/etc/ssl/cert.pem` is used, with the bundled
certifi (2021 roots) only as a fallback, and no bundle at all means no download.

The manifest **cannot name its own payload URL** — both URLs are constants in
the source. A manifest that could point the downloader anywhere would turn a
completeness check into a redirect-to-anywhere. What it does carry is a byte
count and a SHA-256, checked along with `compile()` before anything is written,
and the write is a temp file plus `os.replace` so the live file is never
half-written.

Bookkeeping lives in `update_state.json`, **not** `preferences.json`, because
`save_prefs` rewrites that file from `PREF_DEFAULTS` keys alone and would
destroy any extra key on the next save.

## Finding routines: read the lists, don't grep the binary

Two files on disk document the scripting API, and between them they remove
most of the reason to run `strings` over a binary at all.

- **`~/Library/Application Support/Vectorworks/2026/Plug-ins/VWPluginLibraryRoutines.p`**
  (and `.h`) — generated by Vectorworks into the *user* folder. **866**
  declarations with full signatures and one-line descriptions, covering
  exactly the library-registered routines the main binary's table omits.
  `GetFileN` — the routine whose absence from the main table cost a day — is
  at line 857, documented, with its signature.
- **`Vectorworks.vwr/Strings/ScriptingHelp.vwstrings`** — **2,269** core
  routines across 48 chapters, each with the VS signature, the *Python*
  signature, the chapter and a description.

**The two lists do not overlap: 2,269 + 866 = 3,135 routines.** Quoting 2,269
as the total surface reproduces the GetFileN mistake at a higher level, since
the 866 are precisely the category the main binary leaves out.

**`ScriptingHelp.vwstrings` is UTF-16.** Plain `/usr/bin/grep` cannot match
ASCII against its NUL-interleaved bytes: it exits 1, which reads as a genuine
"not found". `-a` does not help and neither does `strings | grep`. Decode it
first:

```python
text = open(path, 'rb').read().decode('utf-16')
re.findall(r'"Func(\d+)\|([^"]+)" = "(.*?)";', text, re.S)
```

Worse, the `grep` in a Claude Code shell is a ugrep wrapper that decodes UTF-16
silently — so a search that works interactively fails in a script, and any
negative drawn from that file with plain grep is unreliable.

And a name existing is still not a routine existing in the sense you mean:
`vs.Copy` is real, but it is Pascal's substring function `Copy(source, index,
count)`, not a clipboard call. The clipboard route from a script is
`vs.DoMenuTextByName`.

## What cannot be done

**There is no background execution.** No timer, no idle handler, no
document-level event hook, no modeless dialog in the VectorScript API. (The
timer-looking symbols in the binary belong to ImageMagick.) Observing another
vendor's plug-in object requires the C++ SDK — which is how ConnectCAD itself is
built. A menu command runs once and exits.

This matters because ConnectCAD does not push a schematic socket rename out to
the panel connectors pointing at it, and a rename typed into the OIP happens
where no tool can see it.

**Poll and diff is the only route**, and it works because identity is available:
`GetObjectUuid` gives every plug-in object a persistent id. Reconcile Panel
Connectors records each socket's uuid and name; a uuid whose name has changed is
a rename — *known*, not inferred from the names, which is the one thing that
cannot work here since a PanelConnector holds no stable reference to its socket,
only the name as a string.

The snapshot records the **last reconciled state, not the last observed one**. It
refreshes at the end of every run, but a socket whose name has drifted from its
record is outstanding work and its entry is left alone — advancing it on an
unrelated run would erase the only evidence the rename happened. A rename is
settled only once every reference to the old name has been updated.

---

## Safety properties

Design intent, exercised by the test suite against the mock `vs` module. What
has and has not been confirmed in a live drawing is below.

- **Plan → check → write.** Nothing is written until every edit is planned and
  the checks pass, so an abort *during planning* leaves the drawing untouched.
  Once writing has begun there is no rollback of its own — an error mid-write
  stops the chain and reports, but what was already written stays written.
- **Whole-document link resolution**, even when scope is "selected objects only"
  — equipment lives on rack layers while devices live on schematic layers.
- **All writes precede the resets**, and sockets reset *after* their parent so a
  parent reset cannot discard child edits. (ConnectCAD's own rename resets the
  object itself; that is fine for a Device or EquipItem, neither of which has
  child edits here.)
- **Blank is never written over a name, and never used as a match key.** `""` as
  a key would match every unnamed object and rename them all.
- **Socket names are scoped per device.** The same name on two devices is fine;
  twice on one device is reported — a reference to it can no longer say which it
  means.
- **Duplicate device names never block.** The same physical device drawn in
  several places is normal. They are reported, and the report marks which this
  run created.
- **Nothing is written that the user has not seen**, in the tools that show a
  review table.

---

## Verification status

**915 tests** against a mock `vs` module, plus randomised documents: no silent
unlink, no fabricated link, references still resolve, every duplicate reported,
idempotence, sentinel preservation. Dialog defaults are asserted through the real
handlers, so changing one breaks a test.

Confirmed in a live drawing: device and socket creation, socket placement,
`ConnectSelected` wiring, circuits reading back with correct endpoints, the
file dialog, the job path end to end, and that alignment is not required.

Still unverified against a live document:

- **Undo.** The plug-in never calls `BeginUndoEvent`/`EndUndoEvent`, so a run
  is not grouped into one undo event by anything here; how much a single Undo
  takes back is left to Vectorworks and the Plug-in Manager's undo setting, and
  has not been established. Several tools tell the user to "Undo afterwards" —
  that advice rests on an untested assumption. It is the reason the user-facing
  docs say to save and back up before every run rather than relying on Undo.
- **`ControlPoint03X`** as the elbow distance — inferred from two samples.
- **The device label symbol.** Swapping it goes through
  `Utilities::ChangeDevLabelSymbol`, reachable only from the OIP path, so a
  plain `SetRField` on `symbol` is not the whole operation. Left as free text
  rather than a dropdown for that reason — and because a different label symbol
  changes the header height, which socket placement measures.
- **`AlertQuestion` button mapping** — review mode assumes `1 / 0 / 2 / 3`.

Work on a copy until you have seen a preview or a report you agree with.
