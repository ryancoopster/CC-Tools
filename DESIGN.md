# CC Tools — design notes

How ConnectCAD's linking actually works, why these tools are built the way they are, and what has and hasn't been verified. For what the plug-in does and how to install it, see the [README](README.md).

Findings below come from dumping a real 203-device job and from disassembling the ConnectCAD plug-in binary; most of it is not documented publicly.

**One plug-in**, `cc_tools.py`, installed as a single menu command named **CC Tools**. Running it opens a launcher where you tick **one or more** tools to run in sequence:

| Tool | What it does |
|---|---|
| **Dump Fields** | Diagnostic. Read-only. Run after any ConnectCAD update. |
| **Normalise Names** | Uppercase and/or trim names & tags, keeping every name link intact. |
| **Match Names and Display Tags** | Finds Name ≠ Display Tag and lets you pick which wins. |

Each tool still shows its own options dialog; one combined summary appears at the end.

All output goes to `~/Documents/CC Tools/` under **timestamped filenames**.

### Run order is fixed: Dump → Normalise → Match

Tick order doesn't matter — they always run in that sequence, because **normalising first does real work for you**. Uppercasing and trimming collapses every case-only and whitespace-only mismatch (`amp1` vs `AMP1`, `"PROC 2.02 FF "` vs `"PROC 2.02 FF"`), so Match only asks about pairs that genuinely differ. Run it the other way and you'd hand-answer a pile of prompts that Normalise resolves for free.

**A tool that stops halts the chain.** If Normalise refuses to run — a name collision, an unresolved field, an error mid-write — Match is not run, and the summary says so. Whatever tripped it needs looking at before another tool touches the same drawing. Merely *cancelling* a tool's dialog is different: the chain continues to the next one.

### Why one file

Vectorworks creates one `.vsm` per menu command — there is no multi-command plug-in. Shipping the three tools as three commands meant duplicating ~300 lines of shared engine (record readers, document walk, `classify`, the collision logic), so every fix had to land twice and the copies would inevitably drift. The launcher keeps them as one plug-in with one copy of the engine.

Cost: one extra click per run, and no per-tool keyboard shortcuts.

---

## The constraint everything is built around

Most ConnectCAD links are **by name string** — rename one side and the others silently unlink. The diagnostic's name-reference scan found **five** link sites in the reference job, not the one originally assumed:

| Holder | Field | Points at | Count in the reference job |
|---|---|---|---|
| `EquipItem` | `name` | Device name | 17 matched |
| `PanelLayout` | `DeviceName` | Device name | 2 |
| `PanelConnector` | `ConnectedDev` | Device name | 66 |
| `PanelConnector` | `ConnectedSkt` | Socket name | 82 objects |
| `Circuit` | `Src/Dst_Dev_Name`, `Src/Dst_Skt_Name` | cached | 337 |

### Except Device ↔ Equipment, which is a stored reference

`CC_GetEquipmentItem(hDevice)` resolves a **persisted association** — a ref number in the object's tagged data — with no string comparison anywhere. Names are only the bootstrap key ConnectCAD uses to *form* the link.

Earlier versions of these tools inferred that link from name equality. That is wrong in a way that bites precisely where it hurts: with two devices named `SWTCH 4.01`, only one is actually associated with a given equipment item, but name matching claims both — so renaming one device could rename the *other* one's equipment. The reference job has 14 duplicate-name groups, so this was live, not theoretical.

The sync now **asks ConnectCAD** what is linked. If the routine is unavailable (no ConnectCAD licence, or an older build), it falls back to name matching and the report says so in as many words rather than quietly guessing. Run **Dump Fields** to see which path a given setup takes — the API probe reports it, along with every device where the two methods disagree.

Everything else in the table above genuinely *is* keyed on strings, so name matching stays correct there.

All are synced. Circuits are caches, refreshed by resetting every circuit after a rename.

Safety properties, all exercised by the test suite:

- **Plan → check → write.** Nothing is written until every edit is planned and the collision check passes, so an abort leaves the drawing untouched.
- **Whole-document link resolution**, even when scope is "selected objects only".
- **All writes precede all resets**, and sockets reset *after* their parent Device so a parent reset can't discard child edits.
- **Blank is never written over a name, and never used as a match key.** `""` as a lookup key would match every unnamed object and rename them all.
- **Sentinels are never touched** — `<EXT>`, `<DEVICE>`, `---` are placeholders, not names.
- **Socket names are scoped per device** — same socket name in two different devices is fine; twice in one device is blocked.

### Field reference — confirmed by dumping a real job

| Object | Record | Name field | Tag field |
|---|---|---|---|
| Device | `Device` | `name` | `tag` |
| Socket | `Socket` | `name` | `tag` |
| Equipment Item | `EquipItem` | `name` | *(none)* |
| Panel Connector | `PanelConnector` | `SocketName` | `DisplayTag` |

Note ConnectCAD's own inconsistency: `Socket` uses lowercase `name`/`tag`, `PanelConnector` uses `SocketName`/`DisplayTag`. Both are handled.

**`Device-External` is not a device.** Its `name` is always the literal `<EXT>`, and the reference scan confirmed it never holds a device name. It is left alone — renaming it would corrupt a sentinel for no benefit.

### Duplicate device names are allowed

Multiple devices sharing a name is normal here — the same physical device drawn in several places — so **nothing blocks on it**. Duplicates are reported, never refused, and the report marks which ones this run created (`NEW`) versus which already existed.

This is safe now in a way it wasn't before: since Device↔Equipment resolves through ConnectCAD's stored association, a shared name no longer drags the wrong equipment item along. Worth knowing that `PanelConnector`, `PanelLayout` and circuit caches still reference devices *by name*, so a reference to a duplicated name can't say which object it means — and ConnectCAD's own error checker flags duplicates (`DuplicateDevice`).

**One case still stops the run:** two sockets on the *same* device converging on one name. A circuit addresses a socket by name within its device, so identically named sockets on one device are genuinely unaddressable. That's a different thing from two devices sharing a name, and sockets are off by default, so it should rarely fire.

### Unnamed devices — `<DEVICE>`

ConnectCAD parks an **unnamed** device's `name` field at the literal string `<DEVICE>`. In the Geffen Hall file that is **101 of 203 devices**. Two consequences:

- **They are offered, not dropped.** A device with no name but a real Display Tag is exactly the one worth naming, so Match lists it. *Include objects with a blank or `<DEVICE>` side* is **on by default** — it was off originally, which made a working tool look broken. That's safe as a default because the default *action* is "Export list only", which changes nothing. Untick it and the tool still reports how many it skipped, rather than claiming a clean run.
- **A device with neither a name nor a tag is left alone.** There is nothing to copy from. In the Geffen Hall file only 1 of the 101 unnamed devices had a Display Tag, so a correct run changes exactly one device — which looks like failure but isn't.
- **`<DEVICE>` is never a link key.** Renaming one device away from `<DEVICE>` must not drag the partners of the other hundred along with it. `is_unnamed()` treats the placeholder and the empty string identically everywhere: link maps, sync matching, and collision counting all refuse it. 101 devices sharing `<DEVICE>` is 101 blanks, not a duplicate-name collision.

The tools also never *write* `<DEVICE>` onto a device that currently has a real name.

### Behaviour worth understanding

**Normalising can create links that didn't exist.** Device `amp1` and equipment `AMP1` are currently *unlinked* — the strings differ. After uppercasing both become `AMP1` and link up. That's the repair you want, but it's a real structural change. Fuzzing confirms names differing by more than case/whitespace never merge.

**Duplicates never block.** The reference job has four devices named `"A/V Circuit "`. They normalise together to the same new name — still duplicates, no worse than before — and the run proceeds and reports them.

**Whitespace.** In the reference job, 18 names/tags carry stray spaces. Both sides of a pair usually carry the same one, so links still work — it's fragile, not broken. The trim option fixes both sides together.

---

## Install

Once, in Vectorworks 2026:

1. **Tools ▸ Plug-ins ▸ Plug-in Manager…**
2. **New… ▸ Command**, name it **CC Tools**, language **Python**.
3. **Edit Script…**, paste the *entire* `cc_tools.py` — including the final `run_cc_tools()` line, which is what actually runs it — then save.
4. Add it to your workspace: **Tools ▸ Workspaces ▸ Edit Current Workspace ▸ Menus**.

If you previously installed `CC Dump Fields`, `CC Uppercase Names` or `CC Match Names and Tags` as separate commands, delete them in Plug-in Manager — they are superseded.

---

## Using them

Both tools default to **Selected objects only**, so nothing happens document-wide unless you ask for it. Link partners are still resolved across the **whole document** either way — a selection-scoped run never leaves an equipment item, panel or connector holding a stale name.

**Normalise Names** — defaults to *Devices only*, *uppercase + trim*, *sync on*, **Preview off** (it applies). Preview used to default on, which meant a Normalise+Match batch quietly previewed the first half and committed the second. Tick *Preview only* to get a report of what would change without touching anything; the summary then leads with `PREVIEW ONLY - NOTHING WAS CHANGED` so it can't be missed. Sockets are off by default; there are 1,942 of them, so preview that separately before committing.

Note the remaining asymmetry: **Normalise applies by default, Match does not.** Match's default action is *Export list only*, spelled out in the dropdown, because "which side wins" is a judgement call the tool shouldn't make for you.

**Match Names and Display Tags** — defaults to *Devices only*, *include `<DEVICE>`/blank on*, **Export list only**, which writes a CSV with `Differs only by case` and `One side unnamed` columns. Then re-run with a real action:

- *Set Display Tag = Name* — link-safe
- *Set Name = Display Tag* — renames devices, resyncs all five link sites
- *Review one at a time* — **Use Name / Skip / Use Tag / Stop**. Stop abandons the run; it does not commit answers already given.

---

## Verification status

Executed against a mock `vs` module:

- **18 targeted cases** — socket sync, PanelConnector sync, sentinels, trim, per-device socket scoping, blank keys, pre-existing duplicates.
- **15 launcher integration cases** — multi-tool sequencing, normalise-before-match ordering, halt-on-stop, continue-on-cancel, single-tool summary.
- **14 unnamed-device cases** — `<DEVICE>` offered rather than dropped, never used as a link key, never written over a real name, 101 unnamed devices not counted as a collision.
- **14 preview / defaults cases** — preview issues zero writes, preview says so loudly, and every dialog default is asserted through the real handler so changing one breaks a test.
- **14 association cases** — with two devices sharing a name, only the truly-linked equipment item follows; a drifted partner is still found via the stored link; an empty association store reads as "unavailable" rather than "nothing is linked"; panel connectors still resolve by name.
- **2,500 randomised documents** — no silent unlink, no fabricated link, panel and connector refs still resolve, every duplicate reported rather than silent, idempotence, sentinel preservation.

All pass. Every `return` in the three tool entry points is also statically checked to be a 2-tuple, since a stray bare `return` would crash the launcher's unpacking.

That covers the *logic*, not the *Vectorworks API*. Still unverified against a live document:

- **Undo** — whether Cmd+Z reverts a run as one event depends on the Plug-in Manager's undo setting.
- **Circuits** actually re-deriving cached names after `ResetObject`.
- **Socket writes surviving** a parent Device reset. Sockets reset last to avoid this, but it needs a real check — preview first, then test on a copy.
- **`AlertQuestion` button mapping** — review mode assumes `1 / 0 / 2 / 3`.

Work on a copy until you've seen a preview report you agree with.
