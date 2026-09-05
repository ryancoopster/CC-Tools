# CC Tools - a single ConnectCAD utility plug-in for Vectorworks 2026.
#
# ONE menu command. Running it opens a launcher offering three tools:
#   1. Dump Fields          - read-only diagnostic
#   2. Normalise Names      - UPPERCASE and/or trim names & tags
#   3. Match Names and Tags - reconcile Name vs Display Tag
#   4. Spell Check          - fix typos without touching technical vocabulary
#   5. Export Reference     - the drawing as JSON, for use as a worked example
#
# WHY ONE FILE: Vectorworks creates one .vsm per menu command, and there is no
# multi-command plug-in. Keeping the three tools as separate commands meant
# duplicating ~300 lines of shared helpers, so every fix had to land twice.
# A launcher keeps them as one plug-in with one copy of the engine.
#
# ---------------------------------------------------------------------------
# ConnectCAD links objects BY NAME STRING ONLY -- there is no stable ID. The
# reference scan over a real job found five link sites, all synced here:
#
#   EquipItem.name              <-> Device.name
#   PanelLayout.DeviceName       -> Device.name
#   PanelConnector.ConnectedDev  -> Device.name
#   PanelConnector.ConnectedSkt  -> Socket.name  (scoped to its owning device)
#   Circuit.Src/Dst_Dev_Name, _Skt_Name, _Dev_Tag  -> caches, refreshed by reset
#
# Nothing is written until every edit is planned and the collision check has
# passed, so an abort leaves the drawing untouched.
#
# Install: Plug-in Manager > New > Command > name it "CC Tools" >
#   language Python > paste this whole file (including the last line).

import vs
import os
import csv
import time

# ─── Configuration ───────────────────────────────────────────────────────────
BASE_FOLDER = os.path.expanduser('~/Documents/CC Tools')

TYPE_GROUP = 11
TYPE_PIO   = 86

# Field names, most likely first. All CONFIRMED by dumping a real job (Geffen
# Hall ConnectCAD v5). Note ConnectCAD's own inconsistency: Socket uses
# lowercase 'name'/'tag' while PanelConnector uses 'SocketName'/'DisplayTag'.
# The extra candidates are fallbacks for other builds.
DEVICE_NAME_FIELDS  = ['name', 'DeviceName', 'Device Name']
DEVICE_TAG_FIELDS   = ['tag', 'DisplayTag', 'Display Tag']
EQUIP_NAME_FIELDS   = ['name', 'Name', 'EquipName', 'Equipment Name']
SOCKET_NAME_FIELDS  = ['name', 'SocketName', 'Socket Name']
SOCKET_TAG_FIELDS   = ['tag', 'DisplayTag', 'Display Tag']
PANEL_DEVICE_FIELDS = ['DeviceName', 'Device Name']
PCONN_DEVICE_FIELDS = ['ConnectedDev']
PCONN_SOCKET_FIELDS = ['ConnectedSkt']

# ConnectCAD placeholders for "not connected" / "external". They are not names
# and must never seed or receive a rename.
SENTINELS = ('<DEVICE>', '<EXT>', '<SOCKET>', '---')

# Records the diagnostic does not need a full field dump of.
SKIP_RECORDS = ['Title Block Border', 'Callout']
SAMPLES_PER_TYPE = 2

SCOPE_SELECTION = 0
SCOPE_LAYER     = 1
SCOPE_DOCUMENT  = 2

ACTION_EXPORT    = 0
ACTION_NAME_WINS = 1   # Display Tag := Name  (link-safe)
ACTION_TAG_WINS  = 2   # Name := Display Tag  (renames the link key)
ACTION_REVIEW    = 3

TOOL_DUMP      = 0
TOOL_NORMALISE = 1
TOOL_MATCH     = 2
TOOL_SPELL     = 3
TOOL_REFERENCE = 4
TOOL_PROBE     = 5

kOK    = 1
kSetup = 12255


# ═══════════════════════════════════════════════════════════════════════════
# SHARED ENGINE
# ═══════════════════════════════════════════════════════════════════════════

# ─── Record helpers ──────────────────────────────────────────────────────────
def get_pio_name(handle):
    """Return the parametric record name for a plug-in object, or '' if none."""
    param_record = vs.GetParametricRecord(handle)
    if not param_record:
        return ''
    return vs.GetName(param_record) or ''


def get_fields(handle):
    """All parametric fields as an ordered list of (name, value)."""
    param_record = vs.GetParametricRecord(handle)
    if not param_record:
        return []
    pio_name = vs.GetName(param_record)
    fields = []
    for i in range(1, vs.NumFields(param_record) + 1):
        fname = vs.GetFldName(param_record, i)
        if fname:
            fields.append((fname, vs.GetRField(handle, pio_name, fname) or ''))
    return fields


def get_field_names(handle):
    """Just the field names, without reading every value."""
    param_record = vs.GetParametricRecord(handle)
    if not param_record:
        return []
    names = []
    for i in range(1, vs.NumFields(param_record) + 1):
        fname = vs.GetFldName(param_record, i)
        if fname:
            names.append(fname)
    return names


def resolve_field(handle, candidates):
    """Return the first candidate field that actually exists on this object.

    Matching ignores case and spaces so 'Device Name' resolves against a
    'DeviceName' field regardless of which form the build reports."""
    available = get_field_names(handle)
    normalized = {n.lower().replace(' ', ''): n for n in available}
    for candidate in candidates:
        key = candidate.lower().replace(' ', '')
        if key in normalized:
            return normalized[key]
    return None


def read_field(handle, field):
    """Read one parametric field as a string."""
    pio_name = get_pio_name(handle)
    if not pio_name or not field:
        return ''
    return vs.GetRField(handle, pio_name, field) or ''


def write_field(handle, field, value):
    """Write one parametric field. Returns True only if the write landed.

    Refuses to blank a field that currently holds text: names are link keys, so
    an empty write does not merely lose a label, it collapses every affected
    object onto the same empty key. SetRField's own result is honoured rather
    than assumed, so a rejected write is never counted as applied."""
    pio_name = get_pio_name(handle)
    if not pio_name or not field:
        return False
    if not value and read_field(handle, field):
        return False
    result = vs.SetRField(handle, pio_name, field, value)
    # Older builds return None rather than a boolean; treat that as success.
    return True if result is None else bool(result)


def is_unnamed(value):
    """True when a field holds no real name.

    ConnectCAD stores the literal '<DEVICE>' in an unnamed device's name field,
    so an empty string and the placeholder mean the same thing: this object has
    no name. A real job had 101 of 203 devices sitting at '<DEVICE>', so
    treating it as a name would be catastrophic -- it would match every one of
    those devices' partners and rename them all together."""
    return not value or value in SENTINELS


def transform(value, do_upper, do_trim):
    """Apply the requested text normalisation."""
    out = value.strip() if do_trim else value
    return out.upper() if do_upper else out


# ─── Classification ──────────────────────────────────────────────────────────
def classify(handle):
    """Return the ConnectCAD kind of a plug-in object, or None.

    'Device-External' is NOT a device: its name field is always the literal
    '<EXT>' placeholder and the reference scan confirmed it never holds a
    device name, so renaming it would corrupt a sentinel for no benefit."""
    if vs.GetTypeN(handle) != TYPE_PIO:
        return None

    pio = get_pio_name(handle).lower().replace(' ', '')
    if not pio:
        return None

    if pio.startswith('device-external') or 'external' in pio:
        return None
    if pio == 'device' or 'deviceobj' in pio:
        return 'device'
    if pio == 'equipitem' or 'equipitem' in pio or 'equipmentitem' in pio:
        return 'equipment'
    if pio == 'socket' or 'socketobj' in pio:
        return 'socket'
    if pio == 'circuit' or 'circuitobj' in pio:
        return 'circuit'
    if pio == 'panellayout' or 'panellayout' in pio:
        return 'panel'
    if pio == 'panelconnector' or 'panelconnector' in pio:
        return 'panelconnector'
    return None


# ─── Document traversal ──────────────────────────────────────────────────────
def walk_container(container, out, parents, parent, depth=0):
    """Recurse into a container, descending into groups AND plug-in objects.

    `parents` records each object's containing object, which is how a Socket is
    tied back to the Device it belongs to."""
    if depth > 6:
        return
    h = vs.FInGroup(container)
    while h:
        out.append(h)
        parents[h] = parent
        if vs.GetTypeN(h) in (TYPE_GROUP, TYPE_PIO):
            walk_container(h, out, parents, h, depth + 1)
        h = vs.NextObj(h)


def walk_layer(layer, out, parents):
    """Append every object on one layer, descending into groups and PIOs."""
    h = vs.FIn3D(layer)
    while h:
        out.append(h)
        parents[h] = None
        if vs.GetTypeN(h) in (TYPE_GROUP, TYPE_PIO):
            walk_container(h, out, parents, h, 1)
        h = vs.NextObj(h)


def walk_document(with_parents=False):
    """Every object on every design layer, nested contents included."""
    out = []
    parents = {}
    layer = vs.FLayer()
    while layer:
        walk_layer(layer, out, parents)
        layer = vs.NextLayer(layer)
    return (out, parents) if with_parents else out


def owning_device(handle, parents):
    """Walk up from a socket to the Device that contains it."""
    seen = 0
    cur = parents.get(handle)
    while cur is not None and seen < 8:
        if classify(cur) == 'device':
            return cur
        cur = parents.get(cur)
        seen += 1
    return None


def dedupe_handles(handles):
    """Preserve order, drop repeats.

    Vectorworks criteria searches descend into groups, so a selected group and
    its selected members can both come back -- and then walking into the group
    yields the members a second time."""
    seen = set()
    out = []
    for h in handles:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def collect_scope(scope):
    """Collect the handles the user asked to operate on."""
    if scope == SCOPE_SELECTION:
        top = []

        def collect(h):
            top.append(h)
            return True

        vs.ForEachObject(collect, "(SEL=TRUE)")
        out = []
        parents = {}
        for h in top:
            out.append(h)
            if vs.GetTypeN(h) in (TYPE_GROUP, TYPE_PIO):
                walk_container(h, out, parents, h, 1)
        return dedupe_handles(out)

    if scope == SCOPE_LAYER:
        out = []
        walk_layer(vs.ActLayer(), out, {})
        return out

    return walk_document()


def layer_name(handle):
    """Best-effort layer name for a handle."""
    try:
        layer = vs.GetLayer(handle)
        return vs.GetLName(layer) if layer else ''
    except Exception:
        return ''


# ─── Edits ───────────────────────────────────────────────────────────────────
def make_edit(handle, kind, field, old, new, is_link_name):
    """One planned field rewrite.

    `is_link_name` marks the edit as touching a LINK KEY (a device, equipment
    or socket name). Display tags are labels that nothing points at, so they
    must never be mistaken for the object's identity."""
    return {'handle': handle, 'kind': kind, 'field': field,
            'old': old, 'new': new, 'is_link_name': is_link_name}


def cc_routine(name):
    """Return a ConnectCAD scripting routine, or None if unavailable.

    These live in VWPluginLibraryRoutines and are absent without a ConnectCAD
    licence, so every call site must have a fallback."""
    return getattr(vs, name, None)


def linked_equipment(handle):
    """The Equipment Item ConnectCAD says this Device is linked to, or None.

    ConnectCAD does NOT resolve this link by name -- CC_GetEquipmentItem reads a
    stored association (a persistent ref number in the object's tagged data)
    with no string comparison anywhere. Asking it is therefore the only correct
    way to know what is linked; matching on names guesses, and guesses wrongly
    whenever two devices share a name."""
    fn = cc_routine('CC_GetEquipmentItem')
    if fn is None:
        return None
    try:
        result = fn(handle)
    except Exception:
        return None
    return result if result else None


def build_association_map(document):
    """Return (device -> equipment, equipment -> device, available).

    `available` is False when ConnectCAD's association routine is missing or
    answered for no device at all -- typically no ConnectCAD licence. Callers
    then fall back to name matching, which the report flags as a guess."""
    fn = cc_routine('CC_GetEquipmentItem')
    if fn is None:
        return {}, {}, False

    dev_to_equip = {}
    equip_to_dev = {}
    saw_device = False
    for h in document:
        if classify(h) != 'device':
            continue
        saw_device = True
        partner = linked_equipment(h)
        if partner is not None:
            dev_to_equip[h] = partner
            equip_to_dev[partner] = h

    # The routine existing but never answering is indistinguishable from an
    # unlicensed no-op, so treat it as unavailable rather than as "nothing is
    # linked" -- concluding the latter would silently skip every partner.
    if saw_device and not dev_to_equip:
        return {}, {}, False
    return dev_to_equip, equip_to_dev, bool(dev_to_equip)


def link_name_map(edits, kind):
    """old name -> new name for LINK-KEY edits of one object kind.

    Both sides must be non-empty. An empty OLD name cannot identify a partner:
    treating '' as a key would match every blank-named object in the document
    and rename them all to one device's name, fabricating links."""
    return {e['old']: e['new'] for e in edits
            if e['kind'] == kind and e['is_link_name']
            and not is_unnamed(e['old']) and not is_unnamed(e['new'])}


def socket_rename_map(edits, parents):
    """(device name, old socket name) -> new socket name.

    Socket names are only unique within their parent device, so the device name
    has to be part of the key. PanelConnector rows are matched on the same
    pair."""
    out = {}
    for e in edits:
        if e['kind'] != 'socket' or not e['is_link_name']:
            continue
        if is_unnamed(e['old']) or is_unnamed(e['new']):
            continue
        device = owning_device(e['handle'], parents)
        if device is None:
            continue
        field = resolve_field(device, DEVICE_NAME_FIELDS)
        dev_name = read_field(device, field) if field else ''
        if not is_unnamed(dev_name):
            out[(dev_name, e['old'])] = e['new']
    return out


def plan_link_sync(edits, parents):
    """Find partner objects that must follow a rename to preserve their link.

    Runs across the whole document regardless of the user's scope: equipment
    items sit on rack layers while schematic devices sit on schematic layers,
    so a selection-scoped run would otherwise leave the partner behind.

    Returns (sync_edits, used_associations). The device<->equipment pair is
    resolved through ConnectCAD's STORED association where possible, because
    that link is a persisted reference, not a name match -- two devices sharing
    a name would otherwise both claim the same equipment item, and only one of
    them is really linked to it."""
    device_map = link_name_map(edits, 'device')
    equip_map = link_name_map(edits, 'equipment')
    socket_map = socket_rename_map(edits, parents)

    if not device_map and not equip_map and not socket_map:
        return [], True

    sync_edits = []
    document = walk_document()
    dev_to_equip, equip_to_dev, have_assoc = build_association_map(document)
    # Fields the caller is already rewriting, kept as a lookup so a conflicting
    # plan can amend the existing edit instead of silently losing to it.
    # Without this the cascade (equipment -> its device -> that device's
    # equipment) also re-plans the very edit it started from.
    spoken_for = dict(((e['handle'], e['field']), e) for e in edits)

    # Pass 1: equipment renames drag their schematic device along. Collected
    # first because it extends the set of device names that change, which
    # pass 2 depends on.
    if equip_map:
        renamed_equip = {e['handle']: e for e in edits
                         if e['kind'] == 'equipment' and e['is_link_name']}
        if have_assoc:
            # Authoritative: follow the stored association back to its device.
            for equip_handle, edit in renamed_equip.items():
                device = equip_to_dev.get(equip_handle)
                if device is None:
                    continue
                field = resolve_field(device, DEVICE_NAME_FIELDS)
                if not field or (device, field) in spoken_for:
                    continue
                current = read_field(device, field)
                if not is_unnamed(current) and current != edit['new']:
                    sync_edits.append(make_edit(device, 'device', field,
                                                current, edit['new'], True))
        else:
            for h in document:
                if classify(h) != 'device':
                    continue
                field = resolve_field(h, DEVICE_NAME_FIELDS)
                if not field:
                    continue
                current = read_field(h, field)
                if not is_unnamed(current) and current in equip_map \
                        and equip_map[current] != current:
                    sync_edits.append(
                        make_edit(h, 'device', field, current,
                                  equip_map[current], True))

    # Every device name change, whichever pass produced it.
    full_device_map = dict(device_map)
    full_device_map.update(link_name_map(sync_edits, 'device'))

    # Equipment follows its device through the stored association, so a
    # duplicate device name cannot drag an unrelated equipment item along.
    if have_assoc:
        renamed_devices = {e['handle']: e for e in edits + sync_edits
                           if e['kind'] == 'device' and e['is_link_name']}
        # Equipment items that already belong to some device. Nothing outside
        # a device's own association may be claimed from this set.
        spoken_equipment = set(dev_to_equip.values())

        for device_handle, edit in renamed_devices.items():
            partner = dev_to_equip.get(device_handle)

            if partner is None:
                # This device has no stored association. Falling back to name
                # matching for it alone mirrors what ConnectCAD does on rename:
                # a device with no surviving association is re-linked by name.
                # Only UNCLAIMED equipment is eligible, so this can never steal
                # an item that is genuinely associated with another device.
                for h in document:
                    if classify(h) != 'equipment' or h in spoken_equipment:
                        continue
                    field = resolve_field(h, EQUIP_NAME_FIELDS)
                    if not field or (h, field) in spoken_for:
                        continue
                    current = read_field(h, field)
                    if (not is_unnamed(current) and current == edit['old']
                            and current != edit['new']):
                        sync_edits.append(make_edit(h, 'equipment', field,
                                                    current, edit['new'], True))
                continue

            field = resolve_field(partner, EQUIP_NAME_FIELDS)
            if not field:
                continue

            existing = spoken_for.get((partner, field))
            if existing is not None:
                # The equipment item is already being rewritten in its own
                # right -- normalised, say. The device rename has to win:
                # ConnectCAD SEVERS the stored association when a device and
                # its equipment item end up with different names, so letting
                # the independent edit stand would quietly unlink the pair.
                if existing['new'] != edit['new']:
                    existing['new'] = edit['new']
                continue

            current = read_field(partner, field)
            if current != edit['new']:
                sync_edits.append(make_edit(partner, 'equipment', field,
                                            current, edit['new'], True))

    # Pass 2: everything that stores a device or socket name follows it.
    # `old` must be non-empty and not a sentinel -- a blank is not a wildcard.
    for h in document:
        kind = classify(h)

        if kind == 'equipment' and full_device_map and not have_assoc:
            # Fallback only. Without ConnectCAD's association store this is a
            # guess, and it is wrong wherever two devices share a name.
            field = resolve_field(h, EQUIP_NAME_FIELDS)
            if field:
                old = read_field(h, field)
                if not is_unnamed(old) and old in full_device_map \
                        and full_device_map[old] != old:
                    sync_edits.append(
                        make_edit(h, 'equipment', field, old,
                                  full_device_map[old], True))

        elif kind == 'panel' and full_device_map:
            field = resolve_field(h, PANEL_DEVICE_FIELDS)
            if field:
                old = read_field(h, field)
                if not is_unnamed(old) and old in full_device_map \
                        and full_device_map[old] != old:
                    # A reference TO a device, not a link key of its own.
                    sync_edits.append(
                        make_edit(h, 'panel', field, old,
                                  full_device_map[old], False))

        elif kind == 'panelconnector':
            dev_field = resolve_field(h, PCONN_DEVICE_FIELDS)
            skt_field = resolve_field(h, PCONN_SOCKET_FIELDS)
            dev_old = read_field(h, dev_field) if dev_field else ''
            skt_old = read_field(h, skt_field) if skt_field else ''

            # The socket reference is keyed on its ORIGINAL device name, so it
            # is resolved before the device reference is rewritten.
            if skt_field and socket_map and not is_unnamed(dev_old) \
                    and not is_unnamed(skt_old):
                key = (dev_old, skt_old)
                if key in socket_map and socket_map[key] != skt_old:
                    sync_edits.append(
                        make_edit(h, 'panelconnector', skt_field, skt_old,
                                  socket_map[key], False))

            if dev_field and full_device_map and not is_unnamed(dev_old):
                if dev_old in full_device_map and full_device_map[dev_old] != dev_old:
                    sync_edits.append(
                        make_edit(h, 'panelconnector', dev_field, dev_old,
                                  full_device_map[dev_old], False))

    return sync_edits, have_assoc


def dedupe_edits(edits, sync_edits):
    """Drop sync edits that the main pass already covers."""
    seen = set((e['handle'], e['field']) for e in edits)
    return [e for e in sync_edits if (e['handle'], e['field']) not in seen]


# ─── Collision detection ─────────────────────────────────────────────────────
def find_duplicate_names(all_edits):
    """Report every device/equipment name that more than one object will hold.

    INFORMATIONAL ONLY -- this never blocks a run. Multiple devices sharing a
    name is normal in this workflow (one physical device drawn in several
    places), and since Device<->Equipment is now resolved through ConnectCAD's
    stored association rather than by name, a shared name no longer causes the
    wrong equipment item to be renamed.

    Still worth reporting, because PanelConnector, PanelLayout and the circuit
    caches DO key on name strings: a reference to a duplicated name cannot say
    which of the objects it means. ConnectCAD's own error checker flags these
    too (DuplicateDevice, DuplicateEmptyDeviceName).

    Returns {(kind, final_name): {'currents': [...], 'created_here': bool}}
    where created_here means this run merged previously-distinct names.
    """
    renamed = {}
    for e in all_edits:
        if e['is_link_name'] and e['kind'] in ('device', 'equipment'):
            renamed[e['handle']] = e['new']

    final = {}
    for h in walk_document():
        kind = classify(h)
        if kind not in ('device', 'equipment'):
            continue
        fields = DEVICE_NAME_FIELDS if kind == 'device' else EQUIP_NAME_FIELDS
        field = resolve_field(h, fields)
        current = read_field(h, field) if field else ''
        name = renamed.get(h, current)
        # Unnamed objects are not duplicates of each other; 101 devices all
        # sitting at '<DEVICE>' is 101 blanks, not a name clash.
        if is_unnamed(name):
            continue
        final.setdefault((kind, name), []).append((h, current))

    duplicates = {}
    for key, members in final.items():
        if len(members) < 2:
            continue
        currents = [cur for _h, cur in members]
        duplicates[key] = {
            'currents': currents,
            # Distinct originals converging means this run created the
            # duplicate; identical originals were already duplicated.
            'created_here': len(set(currents)) > 1,
        }
    return duplicates


def find_socket_collisions(edits, parents):
    """Detect socket renames that duplicate a name within one device.

    Socket names only need to be unique inside their parent device, so this is
    scoped per device rather than document-wide."""
    renamed = {e['handle']: e['new'] for e in edits
               if e['kind'] == 'socket' and e['is_link_name']}
    if not renamed:
        return {}

    document, doc_parents = walk_document(with_parents=True)
    by_device = {}
    for h in document:
        if classify(h) != 'socket':
            continue
        device = owning_device(h, doc_parents)
        if device is None:
            continue
        field = resolve_field(h, SOCKET_NAME_FIELDS)
        current = read_field(h, field) if field else ''
        name = renamed.get(h, current)
        if is_unnamed(name):
            continue
        by_device.setdefault((device, name), []).append((h, current))

    collisions = {}
    for (device, name), members in by_device.items():
        if len(members) < 2:
            continue
        currents = [cur for _h, cur in members]
        if len(set(currents)) > 1:
            dfield = resolve_field(device, DEVICE_NAME_FIELDS)
            dname = read_field(device, dfield) if dfield else '?'
            collisions[(dname, name)] = currents
    return collisions


# ─── Apply ───────────────────────────────────────────────────────────────────
def apply_edits(edits):
    """Write every planned edit, then reset every touched object.

    All writes happen before any reset, so ConnectCAD never sees a device
    renamed while its partner still holds the old name. Sockets reset last:
    they live inside their parent Device, and resetting a parent after editing
    its children could discard the child edits."""
    applied = []
    touched = []
    for e in edits:
        if write_field(e['handle'], e['field'], e['new']):
            applied.append(e)
            if e['handle'] not in touched:
                touched.append(e['handle'])
    for handle in touched:
        if classify(handle) != 'socket':
            vs.ResetObject(handle)
    for handle in touched:
        if classify(handle) == 'socket':
            vs.ResetObject(handle)
    return applied


def reset_circuits():
    """Reset circuits so their cached device/socket names re-derive.

    Circuits cache Src_Dev_Name, Src_Dev_Tag, Src_Skt_Name, Src_Skt_Tag and the
    Dst_ equivalents. Resetting gives ConnectCAD the chance to refresh them."""
    count = 0
    for h in walk_document():
        if classify(h) == 'circuit':
            vs.ResetObject(h)
            count += 1
    return count


# ─── Output ──────────────────────────────────────────────────────────────────
def save_text(prefix, text, ext='txt'):
    """Write to a timestamped file so runs never overwrite each other."""
    os.makedirs(BASE_FOLDER, exist_ok=True)
    path = os.path.join(BASE_FOLDER, '{}_{}.{}'.format(
        prefix, time.strftime('%Y%m%d_%H%M%S'), ext))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def format_edits(edits):
    return ['  {:<14} {:<14} "{}" -> "{}"'.format(
        e['kind'], e['field'], e['old'], e['new']) for e in edits]


def report_header(title):
    return ['=' * 78,
            'CC TOOLS - {}'.format(title),
            'File: {}'.format(vs.GetFName()),
            'Run:  {}'.format(time.strftime('%Y-%m-%d %H:%M:%S')),
            '=' * 78, '']


# ═══════════════════════════════════════════════════════════════════════════
# TOOL 1: DUMP FIELDS  (read-only diagnostic)
# ═══════════════════════════════════════════════════════════════════════════
def group_by_record(handles):
    """Bucket plug-in object handles by their record name."""
    buckets = {}
    for h in handles:
        if vs.GetTypeN(h) != TYPE_PIO:
            continue
        name = get_pio_name(h)
        if name:
            buckets.setdefault(name, []).append(h)
    return buckets


def collect_device_names(buckets):
    """Every non-empty Device name in the document."""
    names = set()
    for record_name, handles in buckets.items():
        if record_name.lower().replace(' ', '') != 'device':
            continue
        for h in handles:
            field = resolve_field(h, DEVICE_NAME_FIELDS)
            value = read_field(h, field) if field else ''
            if not is_unnamed(value):
                names.add(value)
    return names


def scan_name_references(buckets, device_names):
    """Find every record+field whose value matches a device name.

    This is the important one. A device rename is only safe if we know every
    place that stores the old name. Rather than assume, this reports every
    field in the document holding one -- which is how PanelConnector was
    found."""
    if not device_names:
        return {}

    hits = {}
    for record_name, handles in sorted(buckets.items()):
        if record_name in SKIP_RECORDS:
            continue
        for h in handles:
            for fname, value in get_fields(h):
                if value and value in device_names:
                    key = (record_name, fname)
                    entry = hits.setdefault(key, {'count': 0, 'examples': []})
                    entry['count'] += 1
                    if len(entry['examples']) < 3:
                        entry['examples'].append(value)
    return hits


def find_whitespace_issues(buckets):
    """Flag name values with leading/trailing whitespace.

    Devices and equipment link by exact name match, so a stray space breaks the
    link just as surely as a case difference."""
    issues = []
    targets = [('device', DEVICE_NAME_FIELDS), ('device', DEVICE_TAG_FIELDS),
               ('equipment', EQUIP_NAME_FIELDS), ('socket', SOCKET_NAME_FIELDS)]
    for handles in buckets.values():
        for h in handles:
            kind = classify(h)
            for want_kind, candidates in targets:
                if kind != want_kind:
                    continue
                field = resolve_field(h, candidates)
                if not field:
                    continue
                value = read_field(h, field)
                if value and value != value.strip():
                    issues.append((get_pio_name(h), field, value, layer_name(h)))
    return issues


def probe_connectcad_api(document):
    """Report which ConnectCAD scripting routines work in this document.

    The important line is the DISAGREEMENT count: every device whose stored
    association points at a different equipment item than name-matching would
    pick. Each of those is a case where guessing from names renames the wrong
    object. All of this is read-only -- CC_OnFindAndReplace is deliberately NOT
    called, because it writes."""
    lines = []
    lines.append('--- CONNECTCAD API PROBE ---')

    routines = ['CC_GetEquipmentItem', 'CC_GetDevice', 'CC_GetCircuitSource',
                'CC_GetCircuitDest', 'CC_OnFindAndReplace', 'CC_ReloadData']
    for name in routines:
        lines.append('  {:<22} {}'.format(
            name, 'available' if cc_routine(name) else 'MISSING'))
    lines.append('  {:<22} {}'.format(
        'vs.GetObjectUuid', 'available' if getattr(vs, 'GetObjectUuid', None)
        else 'MISSING'))
    lines.append('')

    devices = [h for h in document if classify(h) == 'device']
    equips = [h for h in document if classify(h) == 'equipment']

    # Name -> equipment items, i.e. what the old name-matching logic would pick.
    by_name = {}
    for h in equips:
        field = resolve_field(h, EQUIP_NAME_FIELDS)
        value = read_field(h, field) if field else ''
        if not is_unnamed(value):
            by_name.setdefault(value, []).append(h)

    linked = 0
    unlinked = 0
    disagree = []
    name_would_guess = 0
    for h in devices:
        field = resolve_field(h, DEVICE_NAME_FIELDS)
        dev_name = read_field(h, field) if field else ''
        partner = linked_equipment(h)
        candidates = by_name.get(dev_name, []) if not is_unnamed(dev_name) else []
        if candidates:
            name_would_guess += 1

        if partner is None:
            unlinked += 1
            # Name matching would have invented a link that does not exist.
            if candidates:
                disagree.append((dev_name, 'no stored link, but {} equipment '
                                 'item(s) share this name'.format(len(candidates))))
            continue

        linked += 1
        if partner not in candidates:
            pfield = resolve_field(partner, EQUIP_NAME_FIELDS)
            pname = read_field(partner, pfield) if pfield else ''
            disagree.append((dev_name, 'linked to equipment named "{}"'.format(pname)))
        elif len(candidates) > 1:
            disagree.append((dev_name, '{} equipment items share this name; only '
                             'one is really linked'.format(len(candidates))))

    lines.append('  Devices: {}   with a stored equipment link: {}   without: {}'.format(
        len(devices), linked, unlinked))
    lines.append('  Devices where name-matching would pick something: {}'.format(
        name_would_guess))
    lines.append('')
    lines.append('  NAME-MATCHING DISAGREES WITH THE STORED LINK: {}'.format(
        len(disagree)))
    if disagree:
        lines.append('  Each of these is a case the old name-based sync got wrong:')
        for dev_name, why in disagree[:25]:
            lines.append('    "{}" -> {}'.format(dev_name, why))
        if len(disagree) > 25:
            lines.append('    ... and {} more'.format(len(disagree) - 25))
    else:
        lines.append('  (none - name matching and the stored links agree here)')
    lines.append('')
    return lines


# ─── Document profile: how this drawing builds devices ───────────────────────
#
# Any generated device has to look like it belongs. Rather than describe house
# style in a prompt, this reads it off the drawing: which make/model pairs are
# actually used, what socket set each one carries, how names and tags are
# constructed, which signals and connectors are in play, and where things live.
#
# Written as JSON so it can be handed to a model verbatim, and summarised in the
# diagnostic report so it is reviewable on its own.

PROFILE_FILE = 'document_profile.json'


def name_pattern(value):
    """Reduce a name to its shape: 'SPK 1.02 HL ARRAY' -> 'AAA 9.99 AA AAAAA'.

    Grouping by shape rather than by text turns 203 individual names into a
    handful of conventions a generator can follow. Masking is per CHARACTER:
    doing it per token leaves the digits intact, so '1.01' and '1.02' come out
    as different conventions and nothing groups at all."""
    out = []
    for ch in value:
        if ch.isalpha():
            out.append('A')
        elif ch.isdigit():
            out.append('9')
        else:
            out.append(ch)
    return ''.join(out)


def socket_signature(device, parents_index):
    """The ordered socket set of one device, as it would need to be recreated."""
    sockets = []
    for h in parents_index.get(device, []):
        if classify(h) != 'socket':
            continue
        sockets.append({
            'name': read_field(h, resolve_field(h, SOCKET_NAME_FIELDS) or ''),
            'type': read_field(h, 'type'),
            'signal': read_field(h, 'signal'),
            'connector': read_field(h, 'connector'),
        })
    return sockets


def build_document_profile(handles, parents):
    """Summarise how this document is built, for reuse when generating objects."""
    # device handle -> its nested sockets
    children = {}
    for h in handles:
        parent = parents.get(h)
        if parent is not None:
            children.setdefault(parent, []).append(h)

    models = {}
    name_shapes = {}
    tag_matches_name = 0
    device_count = 0
    signals = {}
    connectors = {}
    rooms = {}
    racks = {}
    layers = {}
    symbols = {}
    types = {}

    for h in handles:
        kind = classify(h)

        if kind == 'device':
            device_count += 1
            name = read_field(h, resolve_field(h, DEVICE_NAME_FIELDS) or '')
            tag = read_field(h, resolve_field(h, DEVICE_TAG_FIELDS) or '')
            make = read_field(h, 'make')
            model = read_field(h, 'model')
            symbol = read_field(h, 'symbol')
            dtype = read_field(h, 'type')

            if not is_unnamed(name):
                shape = name_pattern(name)
                entry = name_shapes.setdefault(shape, {'count': 0, 'examples': []})
                entry['count'] += 1
                if len(entry['examples']) < 3:
                    entry['examples'].append(name)
            if name and name == tag:
                tag_matches_name += 1

            if make or model:
                key = '{} | {}'.format(make, model)
                entry = models.setdefault(key, {
                    'make': make, 'model': model, 'count': 0,
                    'symbol': symbol, 'type': dtype, 'sockets': None})
                entry['count'] += 1
                if entry['sockets'] is None:
                    sig = socket_signature(h, children)
                    if sig:
                        entry['sockets'] = sig

            for field, bucket in (('loc_room', rooms), ('loc_rack', racks)):
                value = read_field(h, field)
                if value and value not in SENTINELS:
                    bucket[value] = bucket.get(value, 0) + 1
            if symbol:
                symbols[symbol] = symbols.get(symbol, 0) + 1
            if dtype:
                types[dtype] = types.get(dtype, 0) + 1

        elif kind == 'socket':
            for field, bucket in (('signal', signals), ('connector', connectors)):
                value = read_field(h, field)
                if value and value not in SENTINELS:
                    bucket[value] = bucket.get(value, 0) + 1

        if kind in ('device', 'circuit'):
            layer = layer_name(h)
            if layer:
                layers[layer] = layers.get(layer, 0) + 1

    def top(bucket, limit=25):
        return [{'value': k, 'count': v} for k, v in
                sorted(bucket.items(), key=lambda kv: -kv[1])[:limit]]

    return {
        'file': vs.GetFName(),
        'devices': device_count,
        'tag_equals_name': tag_matches_name,
        'name_patterns': [
            {'shape': shape, 'count': info['count'], 'examples': info['examples']}
            for shape, info in sorted(name_shapes.items(), key=lambda kv: -kv[1]['count'])[:15]
        ],
        'device_models': [
            dict(v) for v in sorted(models.values(), key=lambda m: -m['count'])[:40]
        ],
        'signals': top(signals),
        'connectors': top(connectors),
        'rooms': top(rooms),
        'racks': top(racks),
        'layers': top(layers),
        'symbols': top(symbols),
        'device_types': top(types),
    }


def profile_report_lines(profile):
    """The same profile, readable, for the diagnostic report."""
    lines = ['--- DOCUMENT PROFILE (how this drawing builds devices) ---']
    lines.append('Devices: {}   name == tag on {} of them'.format(
        profile['devices'], profile['tag_equals_name']))
    lines.append('')

    lines.append('  Naming conventions (A = letters, 9 = digits):')
    for pattern in profile['name_patterns'][:8]:
        lines.append('    {:<28} x{:<4} e.g. {}'.format(
            pattern['shape'][:28], pattern['count'],
            ', '.join('"{}"'.format(e) for e in pattern['examples'][:2])))
    lines.append('')

    lines.append('  Device models in use, with their socket sets:')
    for model in profile['device_models'][:12]:
        sockets = model.get('sockets') or []
        lines.append('    {:<34} x{:<4} {} socket(s)'.format(
            '{} {}'.format(model['make'], model['model'])[:34],
            model['count'], len(sockets)))
        for socket in sockets[:4]:
            lines.append('        {:<14} {:<5} {:<10} {}'.format(
                socket['name'][:14], socket['type'], socket['signal'],
                socket['connector']))
        if len(sockets) > 4:
            lines.append('        ... and {} more'.format(len(sockets) - 4))
    lines.append('')

    for label, key in (('Signals', 'signals'), ('Connectors', 'connectors'),
                       ('Rooms', 'rooms'), ('Racks', 'racks'),
                       ('Layers', 'layers')):
        values = profile.get(key, [])[:10]
        if values:
            lines.append('  {:<12} {}'.format(
                label + ':', ', '.join('{} ({})'.format(v['value'], v['count'])
                                       for v in values)))
    lines.append('')
    return lines


def build_dump_report():
    lines = report_header('FIELD DUMP')

    all_handles = walk_document()
    buckets = group_by_record(all_handles)

    lines.append('--- RECORD INVENTORY (whole document, nested included) ---')
    lines.append('Total objects visited: {}'.format(len(all_handles)))
    for name in sorted(buckets):
        lines.append('  {:<34} {}'.format(name, len(buckets[name])))
    lines.append('')

    lines.extend(probe_connectcad_api(all_handles))

    _walked, parents = walk_document(with_parents=True)
    profile = build_document_profile(all_handles, parents)
    lines.extend(profile_report_lines(profile))
    try:
        import json as _json
        os.makedirs(BASE_FOLDER, exist_ok=True)
        with open(os.path.join(BASE_FOLDER, PROFILE_FILE), 'w',
                  encoding='utf-8') as f:
            _json.dump(profile, f, indent=2)
    except Exception:
        pass          # the readable section above is the important half

    device_names = collect_device_names(buckets)
    lines.append('--- NAME REFERENCE SCAN ---')
    lines.append('Distinct device names found: {}'.format(len(device_names)))
    lines.append('')
    lines.append('Fields anywhere in the document holding a device name.')
    lines.append('EVERY one of these breaks if a device is renamed without it:')
    lines.append('')
    hits = scan_name_references(buckets, device_names)
    if hits:
        for (record_name, fname), entry in sorted(hits.items()):
            lines.append('  {:<18} . {:<22} {} object(s)'.format(
                record_name, fname, entry['count']))
            for example in entry['examples']:
                lines.append('      e.g. "{}"'.format(example))
    else:
        lines.append('  (none found)')
    lines.append('')

    ws = find_whitespace_issues(buckets)
    lines.append('--- LEADING / TRAILING WHITESPACE IN NAMES ({}) ---'.format(len(ws)))
    if ws:
        lines.append('These are fragile: linking is exact string matching.')
        for record_name, field, value, layer in ws:
            lines.append('  {:<16} {:<10} "{}"   [{}]'.format(
                record_name, field, value, layer or '?'))
    else:
        lines.append('  (none)')
    lines.append('')

    lines.append('--- SAMPLE OBJECTS (up to {} per record type) ---'.format(
        SAMPLES_PER_TYPE))
    lines.append('')
    for record_name in sorted(buckets):
        if record_name in SKIP_RECORDS:
            lines.append('=== {} : skipped (page furniture, {} objects) ==='.format(
                record_name, len(buckets[record_name])))
            lines.append('')
            continue
        for idx, h in enumerate(buckets[record_name][:SAMPLES_PER_TYPE], start=1):
            lines.append('=== {} [sample {}]  layer: {} ==='.format(
                record_name, idx, layer_name(h) or '?'))
            fields = get_fields(h)
            if not fields:
                lines.append('    (no parametric fields)')
            for fname, value in fields:
                # Quoted so trailing spaces and empty strings are visible.
                lines.append('    {:<32} = "{}"'.format(fname, value))
            lines.append('')

    return '\n'.join(lines)


def tool_dump_fields():
    """Read-only diagnostic. Returns (status, summary)."""
    path = save_text('field_dump', build_dump_report())
    return 'done', 'written to\n{}'.format(path)


# ═══════════════════════════════════════════════════════════════════════════
# TOOL 2: NORMALISE NAMES  (uppercase and/or trim)
# ═══════════════════════════════════════════════════════════════════════════
nScopeLbl, nScopePopup = 104, 105
nActionLbl, nUpperChk, nTrimChk = 106, 107, 108
nTargetLbl, nDevicesChk, nEquipChk, nSocketsChk = 109, 110, 111, 112
nSyncChk, nPreviewChk = 113, 114


def plan_renames(handles, do_devices, do_equipment, do_sockets, do_upper, do_trim):
    """Build the list of edits to apply. Returns (edits, unresolved, seen)."""
    edits = []
    # Records a field we expected to find but could not resolve. Without this,
    # a wrong field name makes the tool quietly do nothing and look successful.
    unresolved = {}
    seen_kinds = {}

    for h in handles:
        kind = classify(h)

        if kind == 'device' and do_devices:
            targets = [(DEVICE_NAME_FIELDS, True), (DEVICE_TAG_FIELDS, False)]
        elif kind == 'equipment' and do_equipment:
            targets = [(EQUIP_NAME_FIELDS, True)]
        elif kind == 'socket' and do_sockets:
            targets = [(SOCKET_NAME_FIELDS, True), (SOCKET_TAG_FIELDS, False)]
        else:
            continue

        seen_kinds[kind] = seen_kinds.get(kind, 0) + 1

        for candidates, is_link_name in targets:
            field = resolve_field(h, candidates)
            if not field:
                key = '{} / {}'.format(kind, ' or '.join(candidates))
                unresolved[key] = unresolved.get(key, 0) + 1
                continue
            old = read_field(h, field)
            if is_unnamed(old):
                continue
            new = transform(old, do_upper, do_trim)
            if old == new:
                continue
            edits.append(make_edit(h, kind, field, old, new, is_link_name))

    return edits, unresolved, seen_kinds


def write_normalise_report(edits, sync_edits, socket_col, duplicates,
                           preview, circuits_reset, sync_enabled, failed, label,
                           used_assoc=True):
    lines = report_header('{} {}'.format(
        label.upper(), 'PREVIEW' if preview else 'REPORT'))

    if socket_col:
        lines.append('!!! SOCKET NAME CLASH WITHIN A DEVICE - NOTHING CHANGED !!!')
        lines.append('')
        for (dname, new), currents in sorted(socket_col.items()):
            lines.append('  socket "{}" in device "{}" would be shared by: {}'.format(
                new, dname, ', '.join('"{}"'.format(c) for c in sorted(currents))))
        lines.append('')
        lines.append('A circuit addresses a socket by name within its device, so')
        lines.append('two identically named sockets on one device are ambiguous.')
        lines.append('Rename one by hand, then run again.')
        return '\n'.join(lines)

    lines.append('--- DIRECT EDITS ({}) ---'.format(len(edits)))
    lines.extend(format_edits(edits) or ['  (none)'])
    lines.append('')

    if sync_enabled:
        lines.append('--- LINK SYNC EDITS ({}) ---'.format(len(sync_edits)))
        if used_assoc:
            lines.append("Device<->equipment resolved via ConnectCAD's stored")
            lines.append('association, so duplicate names cannot mis-link.')
        else:
            lines.append('WARNING: ConnectCAD\'s association routine was not')
            lines.append('available, so device<->equipment was matched BY NAME.')
            lines.append('Where two devices share a name that is a guess and may')
            lines.append('rename the wrong equipment item. Check these by hand.')
        lines.extend(format_edits(sync_edits) or ['  (none needed)'])
    else:
        lines.append('--- LINK SYNC: OFF ---')
        link_edits = [e for e in edits if e['is_link_name']]
        if link_edits:
            lines.append('WARNING: {} name(s) changed with sync disabled.'.format(
                len(link_edits)))
            lines.append('Equipment items, panel layouts and panel connectors still')
            lines.append('hold the OLD names, so those links are now BROKEN.')
        else:
            lines.append('No link keys were changed, so nothing needed syncing.')
    lines.append('')

    if duplicates:
        created = {k: v for k, v in duplicates.items() if v['created_here']}
        lines.append('--- DUPLICATE NAMES ({}) ---'.format(len(duplicates)))
        lines.append('Not an error here - the same device drawn in several places')
        lines.append('shares a name by design, and Device<->Equipment is linked by')
        lines.append('stored reference, so a shared name does not mis-link it.')
        lines.append('But PanelConnector, PanelLayout and circuit caches DO key on')
        lines.append('names, so references to these are ambiguous:')
        for (kind, name), info in sorted(duplicates.items()):
            mark = '  NEW' if info['created_here'] else '     '
            lines.append('  {} {} "{}" x{}'.format(
                mark, kind, name, len(info['currents'])))
        if created:
            lines.append('')
            lines.append('  NEW = this run merged previously-distinct names.')
        lines.append('')

    if failed:
        lines.append('--- WRITES REFUSED ({}) ---'.format(len(failed)))
        lines.extend(format_edits(failed))
        lines.append('')

    if not preview:
        lines.append('Circuits reset: {}'.format(circuits_reset))
        lines.append('')

    lines.append('Total changes {}: {}'.format(
        'that would be made' if preview else 'applied',
        len(edits) + len(sync_edits)))
    return '\n'.join(lines)


def ask_normalise_options():
    settings = {}
    dlg = vs.CreateLayout('Normalise ConnectCAD Names', False, 'Run', 'Cancel')

    vs.CreateStaticText(dlg, nScopeLbl, 'Look at:', -1)
    vs.CreatePullDownMenu(dlg, nScopePopup, 26)
    vs.CreateStaticText(dlg, nActionLbl, 'Change:', -1)
    vs.CreateCheckBox(dlg, nUpperChk, 'UPPERCASE')
    vs.CreateCheckBox(dlg, nTrimChk, 'Trim leading / trailing spaces')
    vs.CreateStaticText(dlg, nTargetLbl, 'Apply to:', -1)
    vs.CreateCheckBox(dlg, nDevicesChk, 'Devices  (name + tag)')
    vs.CreateCheckBox(dlg, nEquipChk, 'Equipment Items  (name)')
    vs.CreateCheckBox(dlg, nSocketsChk, 'Sockets  (name + tag)')
    vs.CreateCheckBox(dlg, nSyncChk, 'Keep all name-based links in sync')
    vs.CreateCheckBox(dlg, nPreviewChk,
                      'Preview only - report what WOULD change, change nothing')

    vs.SetFirstLayoutItem(dlg, nScopeLbl)
    vs.SetBelowItem(dlg, nScopeLbl, nScopePopup, 0, 0)
    vs.SetBelowItem(dlg, nScopePopup, nActionLbl, 0, 8)
    vs.SetBelowItem(dlg, nActionLbl, nUpperChk, 0, 0)
    vs.SetBelowItem(dlg, nUpperChk, nTrimChk, 0, 0)
    vs.SetBelowItem(dlg, nTrimChk, nTargetLbl, 0, 8)
    vs.SetBelowItem(dlg, nTargetLbl, nDevicesChk, 0, 0)
    vs.SetBelowItem(dlg, nDevicesChk, nEquipChk, 0, 0)
    vs.SetBelowItem(dlg, nEquipChk, nSocketsChk, 0, 0)
    vs.SetBelowItem(dlg, nSocketsChk, nSyncChk, 0, 8)
    vs.SetBelowItem(dlg, nSyncChk, nPreviewChk, 0, 0)

    def handler(item, data):
        if item == kSetup:
            vs.AddChoice(dlg, nScopePopup, 'Selected objects only', 0)
            vs.AddChoice(dlg, nScopePopup, 'Active layer', 1)
            vs.AddChoice(dlg, nScopePopup, 'Whole document', 2)
            vs.SelectChoice(dlg, nScopePopup, SCOPE_SELECTION, True)
            vs.SetBooleanItem(dlg, nUpperChk, True)
            vs.SetBooleanItem(dlg, nTrimChk, True)
            vs.SetBooleanItem(dlg, nDevicesChk, True)
            vs.SetBooleanItem(dlg, nEquipChk, False)
            vs.SetBooleanItem(dlg, nSocketsChk, False)
            vs.SetBooleanItem(dlg, nSyncChk, True)
            # OFF by default. On meant a run silently changed nothing while a
            # Match in the same batch wrote for real -- the batch half-applied
            # and looked broken. Every run still writes a timestamped report.
            vs.SetBooleanItem(dlg, nPreviewChk, False)
        elif item == kOK:
            settings['scope'] = vs.GetSelectedChoiceIndex(dlg, nScopePopup, 0)
            settings['upper'] = vs.GetBooleanItem(dlg, nUpperChk)
            settings['trim'] = vs.GetBooleanItem(dlg, nTrimChk)
            settings['devices'] = vs.GetBooleanItem(dlg, nDevicesChk)
            settings['equipment'] = vs.GetBooleanItem(dlg, nEquipChk)
            settings['sockets'] = vs.GetBooleanItem(dlg, nSocketsChk)
            settings['sync'] = vs.GetBooleanItem(dlg, nSyncChk)
            settings['preview'] = vs.GetBooleanItem(dlg, nPreviewChk)

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    if not settings:
        vs.AlrtDialog('Could not read the dialog settings - nothing was changed.')
        return None
    return settings


def tool_normalise():
    settings = ask_normalise_options()
    if settings is None:
        return 'cancelled', None

    if not (settings['upper'] or settings['trim']):
        vs.AlrtDialog('Nothing to do. Tick UPPERCASE and/or Trim.')
        return 'cancelled', None
    if not (settings['devices'] or settings['equipment'] or settings['sockets']):
        vs.AlrtDialog('Nothing selected. Tick at least one object type.')
        return 'cancelled', None

    parts = []
    if settings['upper']:
        parts.append('uppercase')
    if settings['trim']:
        parts.append('trim')
    label = ' + '.join(parts)

    handles = collect_scope(settings['scope'])
    if not handles:
        vs.AlrtDialog('No objects found in the chosen scope.')
        return 'cancelled', None

    edits, unresolved, seen_kinds = plan_renames(
        handles, settings['devices'], settings['equipment'], settings['sockets'],
        settings['upper'], settings['trim'])

    if not seen_kinds:
        vs.AlrtDialog(
            'Found {} object(s) in scope, but none were ConnectCAD Devices, '
            'Equipment Items or Sockets.\n\nRun Dump Fields and check the '
            'record inventory.'.format(len(handles)))
        return 'stopped', None

    if unresolved:
        detail = '\n'.join('  {} x{}'.format(key, count)
                           for key, count in sorted(unresolved.items()))
        vs.AlrtDialog(
            'Stopped: could not find the expected field on some objects.\n\n'
            '{}\n\nThese would have been skipped silently. Run Dump Fields and '
            'send the dump so the field names can be corrected.'.format(detail))
        return 'stopped', None

    _doc, parents = walk_document(with_parents=True)

    sync_edits = []
    used_assoc = True
    if settings['sync']:
        planned_sync, used_assoc = plan_link_sync(edits, parents)
        sync_edits = dedupe_edits(edits, planned_sync)

    duplicates = find_duplicate_names(edits + sync_edits)
    # Duplicate DEVICE names no longer stop the run -- they are normal here.
    # Two sockets on ONE device sharing a name still does, because a circuit
    # addresses a socket by name within its device and could not tell them
    # apart. Sockets are off by default, so this rarely fires.
    socket_col = find_socket_collisions(edits, parents)
    if socket_col:
        path = save_text('normalise_report', write_normalise_report(
            edits, sync_edits, socket_col, duplicates,
            settings['preview'], 0, settings['sync'], [], label, used_assoc))
        vs.AlrtDialog(
            'Stopped, nothing changed: {} socket name clash(es) WITHIN a single '
            'device.\n\nA circuit addresses a socket by name within its device, '
            'so two identically named sockets on one device cannot be told '
            'apart.\n\nDetails:\n{}'.format(len(socket_col), path))
        return 'stopped', None

    if not edits and not sync_edits:
        return 'done', 'nothing to change - already clean'

    applied, synced, failed, circuits_reset = edits, sync_edits, [], 0
    if not settings['preview']:
        try:
            planned = edits + sync_edits
            landed = apply_edits(planned)
            keys = set((e['handle'], e['field']) for e in landed)
            applied = [e for e in edits if (e['handle'], e['field']) in keys]
            synced = [e for e in sync_edits if (e['handle'], e['field']) in keys]
            failed = [e for e in planned if (e['handle'], e['field']) not in keys]
            circuits_reset = reset_circuits()
        except Exception as err:
            path = save_text('normalise_report', write_normalise_report(
                edits, sync_edits, {}, duplicates, False, 0,
                settings['sync'], [], label, used_assoc))
            vs.AlrtDialog(
                'ERROR partway through: {}\n\nThe drawing may be partly renamed. '
                'Undo, then check:\n{}'.format(err, path))
            return 'stopped', None

    path = save_text('normalise_report', write_normalise_report(
        applied, synced, {}, duplicates, settings['preview'],
        circuits_reset, settings['sync'], failed, label, used_assoc))

    extra = '\n{} write(s) refused.'.format(len(failed)) if failed else ''
    if duplicates:
        new_dupes = sum(1 for v in duplicates.values() if v['created_here'])
        extra += '\n{} duplicate name(s){} - see report.'.format(
            len(duplicates),
            ', {} new'.format(new_dupes) if new_dupes else '')
    if settings['preview']:
        return 'done', ('PREVIEW ONLY - NOTHING WAS CHANGED.\n'
                        'Would change {} direct, {} link sync.{}\n{}'.format(
                            len(applied), len(synced), extra, path))
    return 'done', 'changed {} direct, {} link sync.{}\n{}'.format(
        len(applied), len(synced), extra, path)


# ═══════════════════════════════════════════════════════════════════════════
# TOOL 3: MATCH NAMES AND TAGS
# ═══════════════════════════════════════════════════════════════════════════
mScopeLbl, mScopePopup = 204, 205
mKindLbl, mDevicesChk, mSocketsChk = 206, 207, 208
mActionLbl, mActionPopup, mEmptyChk = 209, 210, 211


def find_mismatches(handles, do_devices, do_sockets, include_empty):
    """Return (rows, unresolved, seen, skipped_unnamed).

    An object with no name is the single most common case in a real drawing --
    ConnectCAD parks unnamed devices at '<DEVICE>', and one job had 101 of them.
    Those are exactly the ones worth naming from their Display Tag, so they are
    offered rather than discarded; `include_empty` gates them, and the count of
    what was left out is returned so the caller can say so out loud instead of
    reporting a misleadingly clean run."""
    rows = []
    unresolved = 0
    seen = 0
    skipped_unnamed = 0

    for h in handles:
        kind = classify(h)
        if kind == 'device' and do_devices:
            name_field = resolve_field(h, DEVICE_NAME_FIELDS)
            tag_field = resolve_field(h, DEVICE_TAG_FIELDS)
        elif kind == 'socket' and do_sockets:
            name_field = resolve_field(h, SOCKET_NAME_FIELDS)
            tag_field = resolve_field(h, SOCKET_TAG_FIELDS)
        else:
            continue

        seen += 1
        if not name_field or not tag_field:
            unresolved += 1
            continue

        name = read_field(h, name_field)
        tag = read_field(h, tag_field)
        if name == tag:
            continue

        name_missing = is_unnamed(name)
        tag_missing = is_unnamed(tag)
        if name_missing and tag_missing:
            continue                      # nothing on either side to copy
        if (name_missing or tag_missing) and not include_empty:
            skipped_unnamed += 1
            continue

        rows.append({'handle': h, 'kind': kind, 'layer': layer_name(h),
                     'name_field': name_field, 'tag_field': tag_field,
                     'name': name, 'tag': tag})
    return rows, unresolved, seen, skipped_unnamed


def plan_choices(choices):
    """Turn per-row decisions into planned edits. Writes nothing.

    Returns (edits, skipped_blank). A choice whose winning value is empty is
    refused: blanking a device name does not merely lose a label, it collapses
    the device and its equipment item onto an empty link key."""
    edits = []
    skipped_blank = []

    for row, winner in choices:
        if winner == 'name':
            # Name wins: overwrite the tag. Link-safe.
            if is_unnamed(row['name']):
                skipped_blank.append((row, 'tag'))
                continue
            edits.append(make_edit(row['handle'], row['kind'], row['tag_field'],
                                   row['tag'], row['name'], False))
        else:
            # Tag wins: overwrite the name, which is the link key. Writing a
            # placeholder here would park a real device back at '<DEVICE>'.
            if is_unnamed(row['tag']):
                skipped_blank.append((row, 'name'))
                continue
            edits.append(make_edit(row['handle'], row['kind'], row['name_field'],
                                   row['name'], row['tag'], True))

    return edits, skipped_blank


def review_individually(rows):
    """Walk the user through each mismatch.

    Returns (choices, aborted). 'Stop' abandons the whole run rather than
    applying the answers given so far."""
    choices = []
    total = len(rows)

    for idx, row in enumerate(rows, start=1):
        question = '{} {} of {}'.format(row['kind'].capitalize(), idx, total)
        advice = ('Layer: {}\n\n'
                  'Name:        "{}"\n'
                  'Display Tag: "{}"\n\n'
                  'Which one should both use?'.format(
                      row['layer'] or '(unknown)', row['name'], row['tag']))

        # Buttons in order: OK / Cancel / third / fourth.
        answer = vs.AlertQuestion(question, advice, 1,
                                  'Use Name', 'Skip', 'Use Tag', 'Stop')
        if answer == 1:
            choices.append((row, 'name'))
        elif answer == 2:
            choices.append((row, 'tag'))
        elif answer == 3:
            return [], True
        # answer == 0 -> Skip, fall through

    return choices, False


def export_mismatch_csv(rows):
    """Write the mismatch list for review outside Vectorworks."""
    os.makedirs(BASE_FOLDER, exist_ok=True)
    path = os.path.join(BASE_FOLDER, 'name_tag_mismatches_{}.csv'.format(
        time.strftime('%Y%m%d_%H%M%S')))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Kind', 'Layer', 'Name', 'Display Tag',
                         'Differs only by case', 'One side unnamed'])
        for row in rows:
            case_only = (row['name'].upper() == row['tag'].upper()
                         and row['name'] != row['tag'])
            writer.writerow([row['kind'], row['layer'], row['name'], row['tag'],
                             'yes' if case_only else 'no',
                             'yes' if (is_unnamed(row['name'])
                                       or is_unnamed(row['tag'])) else 'no'])
    return path


def write_match_report(applied, synced, skipped_blank, failed, circuits_reset,
                       duplicates, used_assoc=True):
    lines = report_header('NAME / DISPLAY TAG REPORT')

    lines.append('--- CHANGES APPLIED ({}) ---'.format(len(applied)))
    lines.extend(format_edits(applied) or ['  (none)'])
    lines.append('')

    lines.append('--- PARTNERS RESYNCED ({}) ---'.format(len(synced)))
    if used_assoc:
        lines.append("Device<->equipment resolved via ConnectCAD's stored")
        lines.append('association, so duplicate names cannot mis-link.')
    else:
        lines.append("WARNING: ConnectCAD's association routine was not available,")
        lines.append('so device<->equipment was matched BY NAME. Where two devices')
        lines.append('share a name that is a guess. Check these by hand.')
    lines.extend(format_edits(synced) or ['  (none needed)'])
    lines.append('')

    if skipped_blank:
        lines.append('--- REFUSED: WOULD HAVE BLANKED A NAME ({}) ---'.format(
            len(skipped_blank)))
        lines.append('The chosen side was empty. Overwriting a name with a blank')
        lines.append('collapses the link key, so these were left untouched:')
        for row, target in skipped_blank:
            lines.append('  would blank {:<5}  name="{}"  tag="{}"   [{}]'.format(
                target, row['name'], row['tag'], row['layer'] or '?'))
        lines.append('')

    if failed:
        lines.append('--- WRITES REFUSED BY VECTORWORKS ({}) ---'.format(len(failed)))
        lines.extend(format_edits(failed))
        lines.append('')

    if duplicates:
        lines.append('--- DUPLICATE NAMES ({}) ---'.format(len(duplicates)))
        lines.append('Expected in this workflow; reported because PanelConnector,')
        lines.append('PanelLayout and circuit caches reference devices by name:')
        for (kind, name), info in sorted(duplicates.items()):
            mark = '  NEW' if info['created_here'] else '     '
            lines.append('  {} {} "{}" x{}'.format(
                mark, kind, name, len(info['currents'])))
        lines.append('')

    lines.append('Circuits reset: {}'.format(circuits_reset))
    return '\n'.join(lines)


def ask_match_options():
    settings = {}
    dlg = vs.CreateLayout('Match Names and Display Tags', False, 'Continue', 'Cancel')

    vs.CreateStaticText(dlg, mScopeLbl, 'Look at:', -1)
    vs.CreatePullDownMenu(dlg, mScopePopup, 26)
    vs.CreateStaticText(dlg, mKindLbl, 'Check:', -1)
    vs.CreateCheckBox(dlg, mDevicesChk, 'Devices')
    vs.CreateCheckBox(dlg, mSocketsChk, 'Sockets')
    vs.CreateStaticText(dlg, mActionLbl, 'When Name and Tag differ:', -1)
    vs.CreatePullDownMenu(dlg, mActionPopup, 34)
    vs.CreateCheckBox(dlg, mEmptyChk,
                      'Include objects with a blank or <DEVICE> side')

    vs.SetFirstLayoutItem(dlg, mScopeLbl)
    vs.SetBelowItem(dlg, mScopeLbl, mScopePopup, 0, 0)
    vs.SetBelowItem(dlg, mScopePopup, mKindLbl, 0, 8)
    vs.SetBelowItem(dlg, mKindLbl, mDevicesChk, 0, 0)
    vs.SetBelowItem(dlg, mDevicesChk, mSocketsChk, 0, 0)
    vs.SetBelowItem(dlg, mSocketsChk, mActionLbl, 0, 8)
    vs.SetBelowItem(dlg, mActionLbl, mActionPopup, 0, 0)
    vs.SetBelowItem(dlg, mActionPopup, mEmptyChk, 0, 8)

    def handler(item, data):
        if item == kSetup:
            vs.AddChoice(dlg, mScopePopup, 'Selected objects only', 0)
            vs.AddChoice(dlg, mScopePopup, 'Active layer', 1)
            vs.AddChoice(dlg, mScopePopup, 'Whole document', 2)
            # Selection by default, matching Normalise. Link partners are
            # still resolved across the WHOLE document, so a selection-scoped
            # run never leaves an equipment item or panel behind.
            vs.SelectChoice(dlg, mScopePopup, SCOPE_SELECTION, True)

            vs.AddChoice(dlg, mActionPopup, 'Export list only (change nothing)', 0)
            vs.AddChoice(dlg, mActionPopup, 'Set Display Tag = Name (link-safe)', 1)
            vs.AddChoice(dlg, mActionPopup, 'Set Name = Display Tag (renames)', 2)
            vs.AddChoice(dlg, mActionPopup, 'Review one at a time', 3)
            vs.SelectChoice(dlg, mActionPopup, ACTION_EXPORT, True)

            vs.SetBooleanItem(dlg, mDevicesChk, True)
            vs.SetBooleanItem(dlg, mSocketsChk, False)
            # ON by default. Unnamed devices are the common case -- a real job
            # had 101 of 203 sitting at '<DEVICE>' -- and defaulting this off
            # made a working tool look broken. Safe to default on because the
            # default ACTION is "Export list only", which changes nothing.
            vs.SetBooleanItem(dlg, mEmptyChk, True)
        elif item == kOK:
            settings['scope'] = vs.GetSelectedChoiceIndex(dlg, mScopePopup, 0)
            settings['devices'] = vs.GetBooleanItem(dlg, mDevicesChk)
            settings['sockets'] = vs.GetBooleanItem(dlg, mSocketsChk)
            settings['action'] = vs.GetSelectedChoiceIndex(dlg, mActionPopup, 0)
            settings['include_empty'] = vs.GetBooleanItem(dlg, mEmptyChk)

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    if not settings:
        vs.AlrtDialog('Could not read the dialog settings - nothing was changed.')
        return None
    return settings


def tool_match_names_and_tags():
    settings = ask_match_options()
    if settings is None:
        return 'cancelled', None

    if not (settings['devices'] or settings['sockets']):
        vs.AlrtDialog('Nothing to check. Tick Devices and/or Sockets.')
        return 'cancelled', None

    handles = collect_scope(settings['scope'])
    if not handles:
        vs.AlrtDialog('No objects found in the chosen scope.')
        return 'cancelled', None

    rows, unresolved, seen, skipped_unnamed = find_mismatches(
        handles, settings['devices'], settings['sockets'], settings['include_empty'])

    if not seen:
        vs.AlrtDialog(
            'Found {} object(s) in scope, but none were ConnectCAD Devices or '
            'Sockets.\n\nRun Dump Fields and check the record '
            'inventory.'.format(len(handles)))
        return 'stopped', None

    if unresolved:
        vs.AlrtDialog(
            'Stopped: could not find the name/tag fields on {} object(s).\n\n'
            'They would have been skipped silently. Run Dump Fields and send '
            'the dump so the field names can be corrected.'.format(unresolved))
        return 'stopped', None

    if not rows:
        if skipped_unnamed:
            vs.AlrtDialog(
                'No mismatches among named objects, but {} object(s) have no '
                'name (ConnectCAD shows these as "<DEVICE>") or no Display '
                'Tag.\n\nTo name them from their Display Tag, run this again '
                'with "Include objects with a blank or <DEVICE> side" '
                'ticked.'.format(skipped_unnamed))
            return 'done', ('no mismatches among named objects; {} unnamed '
                            'skipped'.format(skipped_unnamed))
        return 'done', 'no mismatches in {} object(s)'.format(seen)

    action = settings['action']

    if action == ACTION_EXPORT:
        path = export_mismatch_csv(rows)
        note = ''
        if skipped_unnamed:
            note = ' ({} unnamed/blank skipped - tick the include box to '
            note = note.format(skipped_unnamed) + 'see them)'
        return 'done', '{} mismatch(es) listed{}\n{}'.format(
            len(rows), note, path)

    if action == ACTION_NAME_WINS:
        choices = [(row, 'name') for row in rows]
    elif action == ACTION_TAG_WINS:
        choices = [(row, 'tag') for row in rows]
    elif action == ACTION_REVIEW:
        choices, aborted = review_individually(rows)
        if aborted:
            return 'cancelled', 'stopped during review, nothing changed'
    else:
        vs.AlrtDialog('Unrecognised action - nothing was changed.')
        return 'stopped', None

    if not choices:
        return 'cancelled', 'no changes chosen'

    # Plan everything before writing anything, so the collision check sees the
    # file's final state including the partner renames.
    _doc, parents = walk_document(with_parents=True)
    edits, skipped_blank = plan_choices(choices)
    planned_sync, used_assoc = plan_link_sync(edits, parents)
    sync_edits = dedupe_edits(edits, planned_sync)

    if not edits:
        vs.AlrtDialog(
            'Nothing applied. All {} chosen change(s) would have blanked a '
            'name, which would break the links.'.format(len(skipped_blank)))
        return 'stopped', None

    duplicates = find_duplicate_names(edits + sync_edits)
    # Duplicate device names are expected in this workflow and do not stop the
    # run; only a socket clash within one device does.
    socket_col = find_socket_collisions(edits, parents)
    if socket_col:
        detail = '\n'.join(
            '  socket "{}" in device "{}" x{}'.format(new, dname, len(currents))
            for (dname, new), currents in sorted(socket_col.items()))
        vs.AlrtDialog(
            'Stopped, nothing changed: {} socket name clash(es) within a single '
            'device.\n\nA circuit addresses a socket by name within its device, '
            'so two identically named sockets on one device cannot be told '
            'apart.\n\n{}'.format(len(socket_col), detail))
        return 'stopped', None

    try:
        planned = edits + sync_edits
        landed = apply_edits(planned)
        keys = set((e['handle'], e['field']) for e in landed)
        applied = [e for e in edits if (e['handle'], e['field']) in keys]
        synced = [e for e in sync_edits if (e['handle'], e['field']) in keys]
        failed = [e for e in planned if (e['handle'], e['field']) not in keys]
        circuits_reset = reset_circuits()
    except Exception as err:
        path = save_text('name_tag_report', write_match_report(
            [], [], skipped_blank, [], 0, duplicates, used_assoc))
        vs.AlrtDialog(
            'ERROR partway through: {}\n\nThe drawing may be partly renamed. '
            'Undo, then check:\n{}'.format(err, path))
        return 'stopped', None

    path = save_text('name_tag_report', write_match_report(
        applied, synced, skipped_blank, failed, circuits_reset, duplicates,
        used_assoc))

    extra = ''
    if skipped_blank:
        extra += '\n{} refused (would have blanked a name).'.format(len(skipped_blank))
    if failed:
        extra += '\n{} write(s) refused by Vectorworks.'.format(len(failed))
    if duplicates:
        new_dupes = sum(1 for v in duplicates.values() if v['created_here'])
        extra += '\n{} duplicate name(s){}.'.format(
            len(duplicates),
            ', {} new'.format(new_dupes) if new_dupes else '')
    return 'done', '{} change(s) applied, {} partner(s) resynced.{}\n{}'.format(
        len(applied), len(synced), extra, path)


# ═══════════════════════════════════════════════════════════════════════════
# TOOL 4: SPELL CHECK
# ═══════════════════════════════════════════════════════════════════════════
#
# The hard part is not finding misspellings, it is NOT flagging the jargon.
# A real job's vocabulary is 'SWTCH', 'AVB Pri', 'EC-6A', 'pCON grey',
# 'NE8FDX-P6-B' -- a dictionary would reject nearly all of it.
#
# So the primary signal comes from the drawing itself: a token used once that
# is one edit away from a token used fifty times is a typo ('Cirrcuit' vs
# 'Circuit'); a token used fifty times consistently is vocabulary, whether or
# not it is a word. A system word list, when present, is used only to spare
# real words from suspicion -- never to condemn a term for being absent.
#
# Corrections are GLOBAL TOKEN SUBSTITUTIONS, not per-object edits. Fixing
# 'Cirrcuit' fixes it identically in every device, socket, equipment item and
# reference at once, which is what keeps name-linked objects linked.

SPELL_IGNORE_FILE = 'spelling_ignore.txt'
SYSTEM_WORDLISTS = ['/usr/share/dict/words', '/usr/dict/words']

# Only FREE-TEXT fields that are typed per instance. Everything else is
# deliberately excluded:
#
#   dropdowns  - signal, connector, type, CircuitType, Cable Type, the symbol
#                fields. These are library vocabularies chosen from a list, not
#                typed, so a "misspelling" would be a value the library rejects.
#   library    - make, model, description. These come from the device database
#                and are identical across every instance of a device.
#   caches     - Circuit Src_*/Dst_* mirror their endpoints and are refreshed on
#                reset; editing them directly would be overwritten anyway.
#   references - loc_room, loc_rack, Src_Room, Dst_Rack point at Room and Rack
#                objects. Renaming one side only would break the reference.
#
# The 'user' fields are included because they are exactly what free-text-per-
# instance means, even though what people put in them varies wildly.
USER_FIELDS = [['user{}'.format(n)] for n in range(1, 9)]

SPELL_FIELDS = {
    'device': ([(DEVICE_NAME_FIELDS, True), (DEVICE_TAG_FIELDS, False)]
               + [(f, False) for f in USER_FIELDS]),
    'socket': ([(SOCKET_NAME_FIELDS, True), (SOCKET_TAG_FIELDS, False)]
               + [(f, False) for f in USER_FIELDS]),
    'equipment': ([(EQUIP_NAME_FIELDS, True)]
                  + [(f, False) for f in USER_FIELDS]),
    'circuit': [(['Label'], False), (['Number'], False), (['Cable'], False)],
}

# Tuning. Rarity is counted in OBJECTS, not field occurrences: one typo
# typically appears in a device's name AND its tag AND its equipment item, so
# counting raw occurrences makes a single mistake look like established usage.
SPELL_MAX_RARE   = 3       # distinct objects carrying the token
SPELL_MIN_COMMON = 4
SPELL_MIN_RATIO  = 4       # correction must be this many times more common
SPELL_MIN_LENGTH = 4       # shorter tokens are abbreviations far more often

kFixIt, kSkipIt, kIgnoreAlways, kStopSpell = 1, 0, 2, 3

ACTION_SPELL_LIST   = 0    # review every term in a dialog, no file involved
ACTION_SPELL_REVIEW = 1    # step through suspected misspellings only
ACTION_SPELL_EXPORT = 2
ACTION_SPELL_VOCAB  = 3    # export every term to a CSV, for bulk work
ACTION_SPELL_APPLY  = 4    # apply the replacements typed into vocabulary.csv
ACTION_SPELL_ALL    = 5


# ─── Text utilities ──────────────────────────────────────────────────────────
def split_tokens(text):
    """Split into alternating separator / letter-run pieces.

    Splitting on letter runs rather than whitespace means 'LAN_IN' yields
    'LAN' and 'IN', and digits stay attached to nothing -- so 'SWTCH 4.01'
    contributes only 'SWTCH'."""
    pieces = []
    current = ''
    current_is_alpha = None
    for ch in text:
        is_alpha = ch.isalpha()
        if current_is_alpha is None or is_alpha == current_is_alpha:
            current += ch
        else:
            pieces.append(current)
            current = ch
        current_is_alpha = is_alpha
    if current:
        pieces.append(current)
    return pieces


def is_word_token(piece):
    return bool(piece) and piece[0].isalpha()


def match_case(original, replacement):
    """Give the replacement the casing pattern of the token it replaces.

    Names are frequently uppercased by the Normalise tool, so a correction
    learned from 'Circuit' must come back as 'CIRCUIT' when it is replacing
    'CIRRCUIT'."""
    if original.isupper():
        return replacement.upper()
    if original.islower():
        return replacement.lower()
    if original[:1].isupper() and original[1:].islower():
        return replacement.capitalize()
    return replacement


def edit_distance(a, b, limit):
    """Levenshtein distance, or None once it provably exceeds `limit`."""
    if abs(len(a) - len(b)) > limit:
        return None
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        best = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            if value < best:
                best = value
        if best > limit:
            return None
        previous = current
    return previous[-1] if previous[-1] <= limit else None


def load_wordlist():
    """A system word list, if this machine has one. Optional by design.

    Used only to EXCUSE a rare token from suspicion when it is a real word --
    never to accuse one. Absence from the list means nothing here, since most
    of the vocabulary is deliberately not English."""
    for path in SYSTEM_WORDLISTS:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return set(line.strip().lower() for line in f if len(line.strip()) > 2)
        except Exception:
            continue
    return set()


def load_ignore_list():
    """Tokens the user has permanently excused, one per line."""
    path = os.path.join(BASE_FOLDER, SPELL_IGNORE_FILE)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return set(line.strip().lower() for line in f
                       if line.strip() and not line.startswith('#'))
    except Exception:
        return set()


def append_ignore_list(tokens):
    """Persist newly excused tokens so later runs stay quiet about them."""
    if not tokens:
        return None
    os.makedirs(BASE_FOLDER, exist_ok=True)
    path = os.path.join(BASE_FOLDER, SPELL_IGNORE_FILE)
    existing = load_ignore_list()
    new = [t for t in sorted(set(tokens)) if t.lower() not in existing]
    if not new:
        return path
    write_header = not os.path.exists(path)
    with open(path, 'a', encoding='utf-8') as f:
        if write_header:
            f.write('# CC Tools - tokens to treat as correct vocabulary.\n')
            f.write('# One per line. Delete a line to start flagging it again.\n')
        for token in new:
            f.write(token + '\n')
    return path


# ─── Harvesting ──────────────────────────────────────────────────────────────
def spell_targets(handle):
    """The (field, is_link_name) pairs this object exposes to the spellchecker."""
    kind = classify(handle)
    out = []
    for candidates, is_link_name in SPELL_FIELDS.get(kind, []):
        field = resolve_field(handle, candidates)
        if field:
            out.append((field, is_link_name))
    return out


def harvest_vocabulary(handles):
    """Survey every token used across every spellcheckable field.

    Returns (frequency, cased, objects):
      frequency - total occurrences, used to judge which of two spellings wins
      cased     - the most common casing, so corrections match house style
      objects   - how many distinct OBJECTS use the token, which is the honest
                  measure of how established it is. A typo in one device shows
                  up in its name, its tag and its equipment item; counting
                  occurrences would read that as three independent uses.
    """
    frequency = {}
    objects = {}
    cased = {}
    for h in handles:
        seen_here = set()
        for field, _is_link in spell_targets(h):
            value = read_field(h, field)
            if not value or value in SENTINELS:
                continue
            for piece in split_tokens(value):
                if not is_word_token(piece) or len(piece) < 2:
                    continue
                key = piece.lower()
                frequency[key] = frequency.get(key, 0) + 1
                seen_here.add(key)
                cased.setdefault(key, {})
                cased[key][piece] = cased[key].get(piece, 0) + 1
        for key in seen_here:
            objects[key] = objects.get(key, 0) + 1
    best_cased = {}
    for key, forms in cased.items():
        best_cased[key] = max(forms.items(), key=lambda kv: kv[1])[0]
    return frequency, best_cased, objects


def find_suspects(frequency, cased, objects, ignore, wordlist):
    """Rare tokens that look like typos of common ones.

    Four things must hold before a token is accused, because a false positive
    here rewrites an engineering drawing:
      - it is rare, and its proposed correction is common
      - the correction is several times more common than it
      - it is not a real word, and not on the user's ignore list
      - it is long enough that an edit-distance match means something
    """
    commons = [(t, c) for t, c in frequency.items() if c >= SPELL_MIN_COMMON]
    commons.sort(key=lambda tc: -tc[1])

    suspects = []
    for token, count in sorted(frequency.items()):
        if objects.get(token, count) > SPELL_MAX_RARE:
            continue
        if len(token) < SPELL_MIN_LENGTH:
            continue
        if token in ignore or token in wordlist:
            continue

        limit = 1 if len(token) < 7 else 2
        best = None
        for candidate, candidate_count in commons:
            if candidate == token or candidate_count < count * SPELL_MIN_RATIO:
                continue
            if candidate in ignore:
                pass          # still a valid correction target
            distance = edit_distance(token, candidate, limit)
            if distance is None:
                continue
            if best is None or distance < best['distance'] or (
                    distance == best['distance'] and candidate_count > best['seen']):
                best = {'suggestion': candidate, 'distance': distance,
                        'seen': candidate_count}
        if best:
            suspects.append({
                'token': token,
                'shown': cased.get(token, token),
                'count': count,
                'objects': objects.get(token, count),
                'suggestion': best['suggestion'],
                'suggestion_shown': cased.get(best['suggestion'], best['suggestion']),
                'seen': best['seen'],
                'distance': best['distance'],
                'source': 'drawing',
            })
    return suspects


# ─── Applying corrections ────────────────────────────────────────────────────
def apply_token_map(text, token_map):
    """Rewrite whole-word tokens, leaving digits, punctuation and case intact."""
    out = []
    for piece in split_tokens(text):
        replacement = token_map.get(piece.lower()) if is_word_token(piece) else None
        out.append(match_case(piece, replacement) if replacement else piece)
    return ''.join(out)


def plan_spelling_edits(handles, token_map, phrase_map=None):
    """Apply the correction map to every spellcheckable field in scope.

    One map applied everywhere is what keeps linked objects linked: a device
    and its equipment item carrying the same typo are corrected in the same
    pass, to the same string, so the link survives the fix rather than being
    repaired afterwards."""
    edits = []
    for h in handles:
        kind = classify(h)
        for field, is_link_name in spell_targets(h):
            old = read_field(h, field)
            if not old or old in SENTINELS:
                continue
            new = apply_phrase_map(old, phrase_map) if phrase_map else old
            new = apply_token_map(new, token_map)
            if new != old:
                edits.append(make_edit(h, kind, field, old, new, is_link_name))
    return edits


# ─── Vocabulary list: spellcheck as find-and-replace ─────────────────────────
#
# Frequency tells you what is CONSISTENT, not what is CORRECT. A term used
# fifty times identically is established usage -- which is exactly what an
# entrenched mistake looks like. 'SWTCH' everywhere is not evidence it is
# right, only that it is habitual.
#
# So alongside the suspect list there is a full vocabulary list: every term in
# the drawing with its usage counts and a blank column to type a replacement
# into. Fill it in a spreadsheet, run the tool again, and every replacement is
# applied globally through the same link-preserving pipeline.

VOCAB_FILE = 'vocabulary.csv'


def export_vocabulary_csv(frequency, cased, objects, suspects):
    """Write every term in the drawing with a blank 'Replace with' column.

    Written twice: a timestamped copy for the record, and a fixed
    `vocabulary.csv` which is the one to edit and the one the apply step
    reads back, so there is never a question of which file is live."""
    suspect_by_token = {s['token']: s for s in suspects}
    rows = []
    for token, count in frequency.items():
        s = suspect_by_token.get(token)
        rows.append([
            cased.get(token, token),
            count,
            objects.get(token, count),
            s['suggestion_shown'] if s else '',
            '',
        ])
    # Rarest first: anything odd is far more likely to be near the top.
    rows.sort(key=lambda r: (r[2], r[1], r[0].lower()))

    header = ['Term', 'Times used', 'Objects', 'Suggested', 'Replace with']
    os.makedirs(BASE_FOLDER, exist_ok=True)
    stamped = os.path.join(BASE_FOLDER, 'vocabulary_{}.csv'.format(
        time.strftime('%Y%m%d_%H%M%S')))
    live = os.path.join(BASE_FOLDER, VOCAB_FILE)
    for path in (stamped, live):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
    return live, len(rows)


def load_vocabulary_csv():
    """Read back the replacements typed into vocabulary.csv.

    Returns (token_map, phrase_map, error). A Term containing a space is
    treated as a literal phrase rather than a word token, so the same sheet
    doubles as a find-and-replace for whole strings."""
    path = os.path.join(BASE_FOLDER, VOCAB_FILE)
    token_map = {}
    phrase_map = {}
    try:
        with open(path, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header or 'Replace with' not in header:
                return {}, {}, 'no "Replace with" column in {}'.format(VOCAB_FILE)
            term_i = header.index('Term')
            repl_i = header.index('Replace with')
            for row in reader:
                if len(row) <= repl_i:
                    continue
                term = row[term_i].strip()
                replacement = row[repl_i].strip()
                if not term or not replacement or term == replacement:
                    continue
                if ' ' in term:
                    phrase_map[term] = replacement
                else:
                    token_map[term.lower()] = replacement
    except FileNotFoundError:
        return {}, {}, '{} not found. Run "Export vocabulary list" first.'.format(
            VOCAB_FILE)
    except Exception as err:
        return {}, {}, 'could not read {}: {}'.format(VOCAB_FILE, err)
    return token_map, phrase_map, None


def apply_phrase_map(text, phrase_map):
    """Literal substring replacement, longest phrase first.

    Longest-first matters: replacing 'Grid Patch' before 'Grid' stops a
    shorter entry from eating the start of a longer one."""
    for phrase in sorted(phrase_map, key=len, reverse=True):
        if phrase in text:
            text = text.replace(phrase, phrase_map[phrase])
    return text


# ─── Review ──────────────────────────────────────────────────────────────────
def review_suspects(suspects):
    """Walk the user through each suspected misspelling.

    Returns (accepted, newly_ignored, aborted). 'Ignore always' answers the
    user's real question -- it excuses every occurrence of that token now AND
    in future runs, so a term like 'SWTCH' is only ever asked about once."""
    accepted = {}
    ignored = []

    for index, suspect in enumerate(suspects, start=1):
        question = 'Possible misspelling {} of {}'.format(index, len(suspects))
        advice = (
            '"{}"  appears {} time(s)\n'
            '"{}"  appears {} time(s)\n\n'
            'Change "{}" to "{}" everywhere?\n\n'
            'Ignore always = treat "{}" as correct vocabulary from now on.'.format(
                suspect['shown'], suspect['count'],
                suspect['suggestion_shown'], suspect['seen'],
                suspect['shown'], suspect['suggestion_shown'],
                suspect['shown']))

        answer = vs.AlertQuestion(question, advice, 1,
                                  'Fix', 'Skip', 'Ignore always', 'Stop')
        if answer == kFixIt:
            accepted[suspect['token']] = suspect['suggestion']
        elif answer == kIgnoreAlways:
            ignored.append(suspect['token'])
        elif answer == kStopSpell:
            return {}, ignored, True
        # kSkipIt -> leave it alone this run, ask again next time

    return accepted, ignored, False


# ─── Output ──────────────────────────────────────────────────────────────────
def export_spelling_csv(suspects):
    os.makedirs(BASE_FOLDER, exist_ok=True)
    path = os.path.join(BASE_FOLDER, 'spelling_{}.csv'.format(
        time.strftime('%Y%m%d_%H%M%S')))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Kind', 'Found', 'Times', 'Suggestion', 'Suggestion seen',
                         'Edit distance'])
        for s in suspects:
            writer.writerow(['spelling', s['shown'], s['count'],
                             s['suggestion_shown'], s['seen'], s['distance']])
    return path


def write_spelling_report(accepted, edits, sync_edits, ignored,
                          duplicates, preview, circuits_reset, used_assoc,
                          failed):
    lines = report_header('SPELL CHECK {}'.format(
        'PREVIEW' if preview else 'REPORT'))

    lines.append('--- CORRECTIONS ({}) ---'.format(len(accepted)))
    lines.append('Each applied to every spellcheckable field in scope, so linked')
    lines.append('objects carrying the same typo are fixed identically:')
    for wrong, right in sorted(accepted.items()):
        lines.append('  "{}" -> "{}"'.format(wrong, right))
    if not accepted:
        lines.append('  (none)')
    lines.append('')

    lines.append('--- FIELDS REWRITTEN ({}) ---'.format(len(edits)))
    lines.extend(format_edits(edits) or ['  (none)'])
    lines.append('')

    lines.append('--- LINK SYNC EDITS ({}) ---'.format(len(sync_edits)))
    if used_assoc:
        lines.append("Device<->equipment resolved via ConnectCAD's stored association.")
    else:
        lines.append("WARNING: ConnectCAD's association routine was unavailable;")
        lines.append('device<->equipment was matched BY NAME. Check these by hand.')
    lines.extend(format_edits(sync_edits) or ['  (none needed)'])
    lines.append('')

    if ignored:
        lines.append('--- ADDED TO THE IGNORE LIST ({}) ---'.format(len(ignored)))
        lines.append('Treated as correct vocabulary from now on. Edit {}'.format(
            SPELL_IGNORE_FILE))
        lines.append('in this folder to change your mind:')
        for token in sorted(ignored):
            lines.append('  {}'.format(token))
        lines.append('')

    if failed:
        lines.append('--- WRITES REFUSED ({}) ---'.format(len(failed)))
        lines.extend(format_edits(failed))
        lines.append('')

    if duplicates:
        lines.append('--- DUPLICATE NAMES ({}) ---'.format(len(duplicates)))
        for (kind, name), info in sorted(duplicates.items()):
            mark = '  NEW' if info['created_here'] else '     '
            lines.append('  {} {} "{}" x{}'.format(
                mark, kind, name, len(info['currents'])))
        lines.append('')

    if not preview:
        lines.append('Circuits reset: {}'.format(circuits_reset))
    return '\n'.join(lines)


# ─── In-dialog vocabulary review ─────────────────────────────────────────────
#
# A list browser shows every term; a separate edit field takes the replacement.
# Vectorworks has no script-accessible in-cell text editing -- the only in-place
# controls a list browser offers are radio and multi-state -- so "click a row,
# type in the box, press Set" is the whole interaction, not a shortcut.
#
# Two documented traps drive the shape of this code:
#   - Arrow keys and type-ahead move the highlight but report rowIndex = -1, so
#     the selected row is re-derived by scanning rather than trusted from the
#     event. Believing the event would write a replacement onto the wrong term.
#   - Sorting reorders rows and invalidates every stored index, so it is turned
#     off. It defaults to ON.

vScope, vLB, vEditLbl, vEdit, vSetBtn, vClearBtn, vHint = 504, 505, 506, 507, 508, 509, 510

kLBSelChangeClick  = -4
kLBUpKey           = -7
kLBDownKey         = -8
kLBAlphaKey        = -9

COL_TERM, COL_USES, COL_OBJECTS, COL_REPLACE = 0, 1, 2, 3


def lb_selected_row(dlg, lb, count):
    """The highlighted row, found by scanning rather than from the event.

    GetLBEventInfo reports rowIndex -1 for arrow-key and type-ahead navigation
    even though the highlight moves, so trusting it would attribute a typed
    replacement to whichever row was last clicked."""
    for i in range(count):
        if vs.IsLBItemSelected(dlg, lb, i):
            return i
    return -1


def lb_cell(dlg, lb, row, col):
    """Read one cell. GetLBItemInfo returns (ok, text, imageIndex)."""
    try:
        ok, text, _image = vs.GetLBItemInfo(dlg, lb, row, col)
        return text if ok else ''
    except Exception:
        return ''


def review_vocabulary_dialog(rows):
    """Show every term with a Replace-with column. Returns {term: replacement}.

    `rows` is [(term, uses, objects)], already ordered -- rarest first, so the
    terms worth a second look are at the top. Returns None if cancelled."""
    state = {'row': -1}
    result = {}
    count = len(rows)

    dlg = vs.CreateLayout('Review Vocabulary', False, 'OK', 'Cancel')

    vs.CreateStaticText(dlg, vScope,
                        'Every term in scope. Select one, type a replacement, '
                        'press Set.', -1)
    vs.CreateLB(dlg, vLB, 92, 22)
    vs.CreateStaticText(dlg, vEditLbl, 'Replace with:', -1)
    vs.CreateEditText(dlg, vEdit, '', 40)
    vs.CreatePushButton(dlg, vSetBtn, 'Set')
    vs.CreatePushButton(dlg, vClearBtn, 'Clear')
    vs.CreateStaticText(dlg, vHint,
                        'Leave a row blank to keep it. Multi-word terms are '
                        'replaced literally.', -1)

    vs.SetFirstLayoutItem(dlg, vScope)
    vs.SetBelowItem(dlg, vScope, vLB, 0, 0)
    vs.SetBelowItem(dlg, vLB, vEditLbl, 0, 8)
    vs.SetBelowItem(dlg, vEditLbl, vEdit, 0, 0)
    vs.SetRightItem(dlg, vEdit, vSetBtn, 4, 0)
    vs.SetRightItem(dlg, vSetBtn, vClearBtn, 4, 0)
    vs.SetBelowItem(dlg, vEdit, vHint, 0, 8)

    def commit_pending():
        """Move whatever is in the edit field onto the row it belongs to."""
        row = state['row']
        if row < 0:
            return
        typed = (vs.GetItemText(dlg, vEdit) or '').strip()
        if typed != lb_cell(dlg, vLB, row, COL_REPLACE):
            vs.SetLBItemInfo(dlg, vLB, row, COL_REPLACE, typed, -1)

    def load_row(row):
        state['row'] = row
        vs.SetItemText(dlg, vEdit, lb_cell(dlg, vLB, row, COL_REPLACE)
                       if row >= 0 else '')

    def handler(item, data):
        if item == kSetup:
            # Columns must be inserted at increasing indices; inserting
            # repeatedly at 0 is a documented header-rendering bug.
            vs.InsertLBColumn(dlg, vLB, COL_TERM, 'Term', 240)
            vs.InsertLBColumn(dlg, vLB, COL_USES, 'Times used', 90)
            vs.InsertLBColumn(dlg, vLB, COL_OBJECTS, 'Objects', 80)
            vs.InsertLBColumn(dlg, vLB, COL_REPLACE, 'Replace with', 240)
            vs.ShowLBHeader(dlg, vLB, True)
            vs.EnableLBColumnLines(dlg, vLB, True)
            vs.EnableLBSingleLineSelection(dlg, vLB, True)
            # OFF deliberately: sorting reorders rows and every stored index
            # goes stale mid-edit. It defaults to ON.
            vs.EnableLBSorting(dlg, vLB, False)

            vs.EnableLBUpdates(dlg, vLB, False)
            for index, (term, uses, objs) in enumerate(rows):
                vs.InsertLBItem(dlg, vLB, index, term)
                vs.SetLBItemInfo(dlg, vLB, index, COL_USES, str(uses), -1)
                vs.SetLBItemInfo(dlg, vLB, index, COL_OBJECTS, str(objs), -1)
                vs.SetLBItemInfo(dlg, vLB, index, COL_REPLACE, '', -1)
            vs.EnableLBUpdates(dlg, vLB, True)
            vs.RefreshLB(dlg, vLB)

        elif item == vLB:
            # GetLBEventInfo is only meaningful inside this branch.
            try:
                ok, event, row, _col = vs.GetLBEventInfo(dlg, vLB)
            except Exception:
                ok, event, row = False, 0, -1
            if event in (kLBUpKey, kLBDownKey, kLBAlphaKey) or row < 0:
                row = lb_selected_row(dlg, vLB, count)
            if row >= 0 and row != state['row']:
                commit_pending()
                load_row(row)

        elif item == vSetBtn:
            if state['row'] < 0:
                row = lb_selected_row(dlg, vLB, count)
                if row >= 0:
                    load_row(row)
            commit_pending()

        elif item == vClearBtn:
            vs.SetItemText(dlg, vEdit, '')
            if state['row'] >= 0:
                vs.SetLBItemInfo(dlg, vLB, state['row'], COL_REPLACE, '', -1)

        elif item == kOK:
            commit_pending()
            for index in range(count):
                term = lb_cell(dlg, vLB, index, COL_TERM)
                replacement = lb_cell(dlg, vLB, index, COL_REPLACE).strip()
                if term and replacement and replacement != term:
                    result[term] = replacement

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    return result


def split_replacements(raw):
    """Sort {term: replacement} into single-word tokens and literal phrases."""
    token_map = {}
    phrase_map = {}
    for term, replacement in raw.items():
        if ' ' in term:
            phrase_map[term] = replacement
        else:
            token_map[term.lower()] = replacement
    return token_map, phrase_map


# ─── Dialog ──────────────────────────────────────────────────────────────────
sScopeLbl, sScopePopup = 404, 405
sActionLbl, sActionPopup = 406, 407
sPreviewChk, sNoteTxt = 408, 409


def ask_spell_options():
    settings = {}
    dlg = vs.CreateLayout('Spell Check ConnectCAD Text', False, 'Continue', 'Cancel')

    vs.CreateStaticText(dlg, sScopeLbl, 'Look at:', -1)
    vs.CreatePullDownMenu(dlg, sScopePopup, 26)
    vs.CreateStaticText(dlg, sActionLbl, 'What to do:', -1)
    vs.CreatePullDownMenu(dlg, sActionPopup, 40)
    vs.CreateCheckBox(dlg, sPreviewChk, 'Preview only - report, change nothing')
    vs.CreateStaticText(
        dlg, sNoteTxt,
        'Free-text fields only - names, tags, user fields, circuit labels.\n'
        'Dropdowns (connector, signal, cable type) are library values and are\n'
        'never touched. Frequency shows what is CONSISTENT, not what is right,\n'
        'so the list lets you override any term, however often it is used.', -1)

    vs.SetFirstLayoutItem(dlg, sScopeLbl)
    vs.SetBelowItem(dlg, sScopeLbl, sScopePopup, 0, 0)
    vs.SetBelowItem(dlg, sScopePopup, sActionLbl, 0, 8)
    vs.SetBelowItem(dlg, sActionLbl, sActionPopup, 0, 0)
    vs.SetBelowItem(dlg, sActionPopup, sPreviewChk, 0, 8)
    vs.SetBelowItem(dlg, sPreviewChk, sNoteTxt, 0, 8)

    def handler(item, data):
        if item == kSetup:
            vs.AddChoice(dlg, sScopePopup, 'Selected objects only', 0)
            vs.AddChoice(dlg, sScopePopup, 'Active layer', 1)
            vs.AddChoice(dlg, sScopePopup, 'Whole document', 2)
            vs.SelectChoice(dlg, sScopePopup, SCOPE_DOCUMENT, True)

            vs.AddChoice(dlg, sActionPopup,
                         'Review all terms in a list (recommended)', 0)
            vs.AddChoice(dlg, sActionPopup,
                         'Review suspected misspellings one at a time', 1)
            vs.AddChoice(dlg, sActionPopup,
                         'Export suspects to CSV (change nothing)', 2)
            vs.AddChoice(dlg, sActionPopup,
                         'Export all terms to CSV (change nothing)', 3)
            vs.AddChoice(dlg, sActionPopup,
                         'Apply replacements from vocabulary.csv', 4)
            vs.AddChoice(dlg, sActionPopup,
                         'Fix every suspect without asking', 5)
            vs.SelectChoice(dlg, sActionPopup, ACTION_SPELL_LIST, True)

            vs.SetBooleanItem(dlg, sPreviewChk, False)
        elif item == kOK:
            settings['scope'] = vs.GetSelectedChoiceIndex(dlg, sScopePopup, 0)
            settings['action'] = vs.GetSelectedChoiceIndex(dlg, sActionPopup, 0)
            settings['preview'] = vs.GetBooleanItem(dlg, sPreviewChk)

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    if not settings:
        vs.AlrtDialog('Could not read the dialog settings - nothing was changed.')
        return None
    return settings


def apply_corrections(handles, token_map, phrase_map, newly_ignored, settings,
                      source='review'):
    """Apply a correction map to the drawing and report. Returns (status, summary).

    Shared by both routes into this tool -- reviewing suspects one at a time,
    and applying replacements typed into vocabulary.csv -- so a term replaced
    by hand goes through exactly the same link-preserving pipeline as one the
    spellchecker suggested."""
    edits = plan_spelling_edits(handles, token_map, phrase_map)
    if not edits:
        return 'done', 'nothing to rewrite - replacements matched no field in scope'

    accepted = dict(token_map)
    accepted.update(phrase_map or {})

    _doc, parents = walk_document(with_parents=True)
    planned_sync, used_assoc = plan_link_sync(edits, parents)
    sync_edits = dedupe_edits(edits, planned_sync)

    duplicates = find_duplicate_names(edits + sync_edits)
    socket_col = find_socket_collisions(edits, parents)
    if socket_col:
        detail = '\n'.join(
            '  socket "{}" in device "{}" x{}'.format(new, dname, len(currents))
            for (dname, new), currents in sorted(socket_col.items()))
        vs.AlrtDialog(
            'Stopped, nothing changed: this would give one device two identically '
            'named sockets, which a circuit cannot tell apart.\n\n{}'.format(detail))
        return 'stopped', None

    applied, synced, failed, circuits_reset = edits, sync_edits, [], 0
    if not settings['preview']:
        try:
            planned = edits + sync_edits
            landed = apply_edits(planned)
            keys = set((e['handle'], e['field']) for e in landed)
            applied = [e for e in edits if (e['handle'], e['field']) in keys]
            synced = [e for e in sync_edits if (e['handle'], e['field']) in keys]
            failed = [e for e in planned if (e['handle'], e['field']) not in keys]
            circuits_reset = reset_circuits()
        except Exception as err:
            path = save_text('spelling_report', write_spelling_report(
                accepted, edits, sync_edits, newly_ignored, duplicates,
                False, 0, used_assoc, []))
            vs.AlrtDialog(
                'ERROR partway through: {}\n\nThe drawing may be partly corrected. '
                'Undo, then check:\n{}'.format(err, path))
            return 'stopped', None

    path = save_text('spelling_report', write_spelling_report(
        accepted, applied, synced, newly_ignored, duplicates,
        settings['preview'], circuits_reset, used_assoc, failed))

    extra = ''
    if source != 'review':
        extra += '\nSource: {}'.format(source)
    if newly_ignored:
        extra += '\n{} added to the ignore list.'.format(len(newly_ignored))
    if failed:
        extra += '\n{} write(s) refused.'.format(len(failed))

    if settings['preview']:
        return 'done', ('PREVIEW ONLY - NOTHING WAS CHANGED.\n'
                        'Would apply {} replacement(s) to {} field(s), {} link '
                        'sync.{}\n{}'.format(len(accepted), len(applied),
                                              len(synced), extra, path))
    return 'done', '{} replacement(s) applied to {} field(s), {} link sync.{}\n{}'.format(
        len(accepted), len(applied), len(synced), extra, path)


# ─── Menu tool: Spell Check ──────────────────────────────────────────────────
def tool_spellcheck():
    """Returns (status, summary)."""
    settings = ask_spell_options()
    if settings is None:
        return 'cancelled', None

    handles = collect_scope(settings['scope'])
    if not handles:
        vs.AlrtDialog('No objects found in the chosen scope.')
        return 'cancelled', None

    frequency, cased, objects = harvest_vocabulary(handles)
    if not frequency:
        vs.AlrtDialog(
            'Found {} object(s) in scope, but no readable text on any of them.\n\n'
            'Run Dump Fields and check the record inventory.'.format(len(handles)))
        return 'stopped', None

    ignore = load_ignore_list()
    wordlist = load_wordlist()
    suspects = find_suspects(frequency, cased, objects, ignore, wordlist)
    if not suspects:
        return 'done', 'no suspected misspellings in {} distinct word(s)'.format(
            len(frequency))

    if settings['action'] == ACTION_SPELL_LIST:
        suspect_by_token = {s['token']: s for s in suspects}
        # Rarest first, so anything odd is near the top rather than buried
        # among hundreds of settled terms.
        ordered = sorted(frequency,
                         key=lambda t: (objects.get(t, frequency[t]),
                                        frequency[t], t))
        listed = [(cased.get(t, t), frequency[t], objects.get(t, frequency[t]))
                  for t in ordered]
        raw = review_vocabulary_dialog(listed)
        if raw is None:
            return 'cancelled', 'closed the vocabulary list, nothing changed'
        if not raw:
            return 'done', ('reviewed {} term(s), no replacements '
                            'entered'.format(len(listed)))
        token_map, phrase_map = split_replacements(raw)
        return apply_corrections(handles, token_map, phrase_map, [], settings,
                                 source='vocabulary list')

    if settings['action'] == ACTION_SPELL_VOCAB:
        path, count = export_vocabulary_csv(frequency, cased, objects, suspects)
        return 'done', ('{} term(s) written to\n{}\n\nType replacements into the '
                        '"Replace with" column, save, then run again with '
                        '"Apply replacements".'.format(count, path))

    if settings['action'] == ACTION_SPELL_EXPORT:
        path = export_spelling_csv(suspects)
        return 'done', '{} suspect(s) listed in\n{}'.format(len(suspects), path)

    if settings['action'] == ACTION_SPELL_REVIEW:
        accepted, newly_ignored, aborted = review_suspects(suspects)
        if aborted:
            append_ignore_list(newly_ignored)
            vs.AlrtDialog('Stopped. Nothing was changed.')
            return 'cancelled', 'stopped during review, nothing changed'
    else:
        accepted = {s['token']: s['suggestion'] for s in suspects}
        newly_ignored = []

    ignore_path = append_ignore_list(newly_ignored)

    if not accepted:
        summary = 'no corrections chosen'
        if newly_ignored:
            summary += '; {} token(s) added to the ignore list'.format(
                len(newly_ignored))
        return 'done', summary

    return apply_corrections(handles, accepted, {}, newly_ignored,
                             settings)

# ═══════════════════════════════════════════════════════════════════════════
# TOOL 5: EXPORT REFERENCE SCHEMATIC
# ═══════════════════════════════════════════════════════════════════════════
#
# Turns part of an existing drawing into the same JSON shape a generator would
# have to produce: devices with their sockets, and circuits with their real
# endpoints. Examples in the exact output format are the most useful thing you
# can put in front of a model -- far more so than a picture of the finished
# sheet, and far cheaper than one.
#
# Circuit endpoints come from CC_GetCircuitSource / CC_GetCircuitDest, which
# read ConnectCAD's stored association. The Src_Dev_Name / Dst_Skt_Name fields
# are derived output refreshed on reset, so a drawing mid-edit can have them
# stale -- asking the association is the only way to know what is really wired
# to what.
#
# Read-only. Scope it to the schematic layer: a location plan contributes
# nothing a signal flow needs, and a big drawing set is mostly plans.

REFERENCE_FOLDER = 'reference'


def device_local_sockets(device):
    """The sockets belonging to one device, read from its profile group.

    ConnectCAD keeps a device's sockets in the plug-in object's profile group
    rather than loose on the layer, which is also where they must be written
    when creating one."""
    sockets = []
    getter = getattr(vs, 'GetCustomObjectProfileGroup', None)
    if getter is None:
        return sockets
    try:
        group = getter(device)
    except Exception:
        return sockets
    if not group:
        return sockets

    handle = vs.FInGroup(group)
    guard = 0
    while handle and guard < 500:
        guard += 1
        if classify(handle) == 'socket':
            name_field = resolve_field(handle, SOCKET_NAME_FIELDS)
            sockets.append({
                'name': read_field(handle, name_field) if name_field else '',
                'type': read_field(handle, 'type'),
                'signal': read_field(handle, 'signal'),
                'connector': read_field(handle, 'connector'),
            })
        handle = vs.NextObj(handle)
    return sockets


def circuit_endpoints(circuit, device_ids=None):
    """(source, destination) for one circuit, or None where truly unconnected.

    CC_GetCircuitSource / CC_GetCircuitDest hand back four handles:
    (device, device socket, adapter, terminal socket). The adapter slot matters
    -- a circuit landing on an adapter rather than straight onto a device would
    otherwise read as unconnected.

    An UNNAMED device is still a device. ConnectCAD parks unnamed devices at
    '<DEVICE>', and a drawing can be more than half of them, so judging
    connectivity by whether a name came back reports real wiring as dangling.
    Presence of the handle decides connected-ness; the name is just a label.

    Reads the stored association, not the cached Src_*/Dst_* fields, which are
    derived output and go stale between resets."""
    def name_of(handle, candidates):
        if not handle:
            return ''
        field = resolve_field(handle, candidates)
        return read_field(handle, field) if field else ''

    def describe(result):
        if not isinstance(result, (list, tuple)) or not result:
            return None
        device = result[0] if len(result) > 0 else None
        dev_socket = result[1] if len(result) > 1 else None
        adapter = result[2] if len(result) > 2 else None
        end_socket = result[3] if len(result) > 3 else None

        if not (device or dev_socket or adapter or end_socket):
            return None               # nothing on this end at all

        socket = dev_socket or end_socket
        out = {'connected': True}

        if device:
            name = name_of(device, DEVICE_NAME_FIELDS)
            # Resolve through the same id the device list uses, so an unnamed
            # device is still referable rather than an empty string.
            if device_ids is not None and device in device_ids:
                out['device'] = device_ids[device]
            else:
                out['device'] = name
            if is_unnamed(name):
                out['device_unnamed'] = True
        else:
            out['device'] = None

        if socket:
            out['socket'] = name_of(socket, SOCKET_NAME_FIELDS)
            out['signal'] = read_field(socket, 'signal')
        if adapter:
            out['adapter'] = name_of(adapter, DEVICE_NAME_FIELDS) or '(unnamed)'
            if end_socket and end_socket is not socket:
                out['adapter_socket'] = name_of(end_socket, SOCKET_NAME_FIELDS)
        return out

    def call(routine_name):
        routine = cc_routine(routine_name)
        if routine is None:
            return None
        # The documented shape takes only the circuit; some builds expose a
        # skip-adapters flag. Try the documented form first.
        for args in ((circuit,), (circuit, False)):
            try:
                return describe(routine(*args))
            except TypeError:
                continue
            except Exception:
                return None
        return None

    return call('CC_GetCircuitSource'), call('CC_GetCircuitDest')


def build_reference(handles):
    """The drawing as structured data: devices, their sockets, and the wiring.

    Devices are collected first so every circuit endpoint can be resolved to an
    id, including unnamed ones -- otherwise circuits would reference objects
    missing from the file."""
    devices = []
    device_ids = {}
    circuits = []
    half_wired = []
    unwired = 0
    unnamed_count = 0

    for h in handles:
        if classify(h) != 'device':
            continue
        name_field = resolve_field(h, DEVICE_NAME_FIELDS)
        tag_field = resolve_field(h, DEVICE_TAG_FIELDS)
        name = read_field(h, name_field) if name_field else ''

        if is_unnamed(name):
            unnamed_count += 1
            identifier = '<unnamed {}>'.format(unnamed_count)
        else:
            identifier = name
        device_ids[h] = identifier

        devices.append({
            'id': identifier,
            'name': name,
            'unnamed': is_unnamed(name),
            'tag': read_field(h, tag_field) if tag_field else '',
            'make': read_field(h, 'make'),
            'model': read_field(h, 'model'),
            'type': read_field(h, 'type'),
            'room': read_field(h, 'loc_room'),
            'rack': read_field(h, 'loc_rack'),
            'rack_u': read_field(h, 'loc_rackU'),
            'layer': layer_name(h),
            'sockets': device_local_sockets(h),
        })

    for h in handles:
        if classify(h) != 'circuit':
            continue
        source, destination = circuit_endpoints(h, device_ids)
        if source is None and destination is None:
            unwired += 1
            continue
        record = {
            'signal': read_field(h, 'Signal'),
            'label': read_field(h, 'Label'),
            'number': read_field(h, 'Number'),
            'from': source,
            'to': destination,
        }
        circuits.append(record)
        # Only a MISSING end counts as half wired. A device with no name is
        # still a device.
        if source is None or destination is None:
            half_wired.append(record)

    return {
        'file': vs.GetFName(),
        'exported': time.strftime('%Y-%m-%d %H:%M:%S'),
        'devices': devices,
        'unnamed_devices': unnamed_count,
        'circuits': circuits,
        'unwired_circuits': unwired,
        # One end genuinely absent -- not merely attached to something unnamed.
        'half_wired_circuits': half_wired,
    }


def save_reference(reference, label):
    """Write to reference/<label>.json, alongside the other CC Tools output."""
    import json
    folder = os.path.join(BASE_FOLDER, REFERENCE_FOLDER)
    os.makedirs(folder, exist_ok=True)
    safe = ''.join(ch if (ch.isalnum() or ch in ' -_') else '_' for ch in label)
    path = os.path.join(folder, '{}_{}.json'.format(
        safe.strip() or 'reference', time.strftime('%Y%m%d_%H%M%S')))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(reference, f, indent=2)
    return path


rScopeLbl, rScopePopup, rNoteTxt = 704, 705, 706


def ask_reference_options():
    settings = {}
    dlg = vs.CreateLayout('Export Reference Schematic', False, 'Export', 'Cancel')

    vs.CreateStaticText(dlg, rScopeLbl, 'Export from:', -1)
    vs.CreatePullDownMenu(dlg, rScopePopup, 26)
    vs.CreateStaticText(
        dlg, rNoteTxt,
        'Read-only. Writes devices, their sockets and the real circuit wiring\n'
        'to reference/ as JSON, for use as a worked example.\n\n'
        'Point it at a SIGNAL FLOW layer. Location plans and elevations carry\n'
        'no wiring, so exporting them costs tokens later and teaches nothing.', -1)

    vs.SetFirstLayoutItem(dlg, rScopeLbl)
    vs.SetBelowItem(dlg, rScopeLbl, rScopePopup, 0, 0)
    vs.SetBelowItem(dlg, rScopePopup, rNoteTxt, 0, 8)

    def handler(item, data):
        if item == kSetup:
            vs.AddChoice(dlg, rScopePopup, 'Selected objects only', 0)
            vs.AddChoice(dlg, rScopePopup, 'Active layer', 1)
            vs.AddChoice(dlg, rScopePopup, 'Whole document', 2)
            vs.SelectChoice(dlg, rScopePopup, SCOPE_LAYER, True)
        elif item == kOK:
            settings['scope'] = vs.GetSelectedChoiceIndex(dlg, rScopePopup, 0)

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    if not settings:
        vs.AlrtDialog('Could not read the dialog settings - nothing was exported.')
        return None
    return settings


def tool_export_reference():
    """Returns (status, summary)."""
    settings = ask_reference_options()
    if settings is None:
        return 'cancelled', None

    handles = collect_scope(settings['scope'])
    if not handles:
        vs.AlrtDialog('No objects found in the chosen scope.')
        return 'cancelled', None

    reference = build_reference(handles)
    if not reference['devices']:
        vs.AlrtDialog(
            'Found {} object(s), but no named ConnectCAD devices.\n\n'
            'This looks like a location plan rather than a signal flow. Switch '
            'to a schematic layer and try again.'.format(len(handles)))
        return 'done', 'no devices in scope - wrong layer?'

    label = layer_name(handles[0]) or 'reference'
    path = save_reference(reference, label)

    wired = len(reference['circuits'])
    note = ''
    if reference['unwired_circuits']:
        note = '\n{} circuit(s) had no stored connection and were skipped.'.format(
            reference['unwired_circuits'])
    if reference['half_wired_circuits']:
        note += '\n{} circuit(s) are connected at ONE end only.'.format(
            len(reference['half_wired_circuits']))
    if not wired and not cc_routine('CC_GetCircuitSource'):
        note += ('\nConnectCAD\'s circuit routines were unavailable, so no '
                 'wiring could be read.')

    return 'done', '{} device(s), {} circuit(s).{}\n{}'.format(
        len(reference['devices']), wired, note, path)


# ═══════════════════════════════════════════════════════════════════════════
# TOOL 6: CREATION PROBE  (writes objects — run on a scratch file)
# ═══════════════════════════════════════════════════════════════════════════
#
# Everything this plug-in READS has been verified against a real drawing.
# Everything it would WRITE when generating a schematic is still inference from
# disassembling the ConnectCAD binary. This runs that write path once, on two
# throwaway devices, and reports exactly which steps worked.
#
# Three unverified claims, in order of how much rests on them:
#   1. CC_DeviceFromShape turns a rectangle into a bare Device.
#   2. A Socket PIO duplicated into the device's profile group becomes a real
#      socket -- there is no socket-creation routine, so this is the only way.
#   3. Selecting two devices and running ConnectSelected wires horizontally
#      aligned sockets, since script cannot write the association directly.
#
# If 3 fails, a generator cannot wire anything and the whole feature changes
# shape. Better to learn that from two rectangles than from a finished tool.

TYPE_SYMDEF = 16
DEFAULTS_FOLDER = 14          # BuildResourceList: Defaults folder
SOCKET_SYMBOLS = ['skt_R', 'skt_L', 'skt_R_loop', 'skt_L_loop']
PROBE_PREFIX = 'CCTOOLS PROBE'


def import_socket_symbol(name):
    """Find or import one socket symbol definition. Returns a handle or None.

    ConnectCAD imports these on demand from Libraries/Defaults/ConnectCAD/
    Socket; from script the import has to be done explicitly."""
    existing = vs.GetObject(name)
    if existing and vs.GetTypeN(existing) == TYPE_SYMDEF:
        return existing
    try:
        list_id, count = vs.BuildResourceList(TYPE_SYMDEF, DEFAULTS_FOLDER,
                                              'ConnectCAD/Socket')
    except Exception:
        return None
    for index in range(1, (count or 0) + 1):
        try:
            if vs.GetNameFromResourceList(list_id, index) == name:
                return vs.ImportResourceToCurrentFile(list_id, index)
        except Exception:
            continue
    return None


def socket_prototype(symbol):
    """The Socket plug-in object inside a socket symbol definition."""
    handle = vs.FInSymDef(symbol)
    guard = 0
    while handle and guard < 50:
        guard += 1
        if vs.GetTypeN(handle) == TYPE_PIO:
            return handle
        handle = vs.NextObj(handle)
    return None


def probe_make_device(name, x, y, width, height, socket_specs, log):
    """Create one device with sockets.

    Returns (device handle or None, every socket added). The second value
    matters: a device that comes back without its sockets is a failure, and
    reporting it as anything else would defeat the point of a probe."""
    try:
        vs.Rect(x - width / 2.0, y + height, x + width / 2.0, y)
        rect = vs.LNewObj()
    except Exception as err:
        log.append('  FAIL  could not draw the rectangle: {}'.format(err))
        return None, False
    if not rect:
        log.append('  FAIL  no rectangle handle came back')
        return None, False

    maker = cc_routine('CC_DeviceFromShape')
    if maker is None:
        log.append('  FAIL  CC_DeviceFromShape is unavailable (ConnectCAD licence?)')
        return None, False
    try:
        device = maker(rect)
    except Exception as err:
        log.append('  FAIL  CC_DeviceFromShape raised: {}'.format(err))
        return None, False
    if not device:
        log.append('  FAIL  CC_DeviceFromShape returned nothing')
        return None, False
    log.append('  ok    device created from rectangle')

    for field, value in (('name', name), ('tag', name),
                         ('make', 'CC Tools'), ('model', 'Probe')):
        write_field(device, field, value)
    log.append('  ok    name/make/model set')

    group_getter = getattr(vs, 'GetCustomObjectProfileGroup', None)
    if group_getter is None:
        log.append('  FAIL  GetCustomObjectProfileGroup is unavailable')
        return device, False
    try:
        group = group_getter(device)
    except Exception as err:
        log.append('  FAIL  profile group unreadable: {}'.format(err))
        return device, False
    if not group:
        log.append('  FAIL  device has no profile group')
        return device, False
    log.append('  ok    profile group found')

    made = 0
    for symbol_name, socket_name, socket_type, offset in socket_specs:
        symbol = import_socket_symbol(symbol_name)
        if not symbol:
            log.append('  FAIL  socket symbol {} not found'.format(symbol_name))
            continue
        prototype = socket_prototype(symbol)
        if not prototype:
            log.append('  FAIL  no Socket object inside {}'.format(symbol_name))
            continue
        try:
            # SetParent cannot move an object into a plug-in container;
            # CreateDuplicateObject is the documented way in.
            socket = vs.CreateDuplicateObject(prototype, group)
        except Exception as err:
            log.append('  FAIL  duplicating the socket raised: {}'.format(err))
            continue
        if not socket:
            log.append('  FAIL  duplicate returned nothing')
            continue
        # Coordinates are device-local, origin at the bottom centre of the
        # rectangle the device was made from.
        try:
            vs.HMove(socket, width / 2.0, offset)
        except Exception:
            pass
        write_field(socket, 'name', socket_name)
        write_field(socket, 'tag', socket_name)
        write_field(socket, 'type', socket_type)
        try:
            vs.ResetObject(socket)
        except Exception:
            pass
        made += 1

    log.append('  {}    {} of {} socket(s) added'.format(
        'ok  ' if made == len(socket_specs) else 'PART', made, len(socket_specs)))
    try:
        vs.ResetObject(device)
    except Exception:
        pass
    return device, made == len(socket_specs)


def probe_connect(first, second, log):
    """Try ConnectSelected, then verify with the association reader."""
    command = getattr(vs, 'DoMenuTextByName', None)
    if command is None:
        log.append('  FAIL  DoMenuTextByName is unavailable')
        return False
    try:
        vs.DSelectAll()
        vs.SetSelect(first)
        vs.SetSelect(second)
        command('ConnectSelected', 0)
        log.append('  ok    ConnectSelected ran without error')
    except Exception as err:
        log.append('  FAIL  ConnectSelected raised: {}'.format(err))
        return False

    # A circuit only counts as made if the association reader can see it.
    found = 0
    for handle in walk_document():
        if classify(handle) != 'circuit':
            continue
        source, destination = circuit_endpoints(handle)
        names = []
        for end in (source, destination):
            if end and end.get('device'):
                names.append(str(end['device']))
        if any(n.startswith(PROBE_PREFIX) for n in names):
            found += 1
            log.append('  ok    circuit wired: {}'.format(' -> '.join(names)))
    if not found:
        log.append('  FAIL  no circuit connecting the probe devices was found')
    return found > 0


def tool_creation_probe():
    """Returns (status, summary)."""
    if vs.AlertQuestion(
            'Run the creation probe?',
            'This WRITES two throwaway devices and tries to wire them, to check '
            'whether generating schematics is possible at all.\n\n'
            'Run it on a scratch file, not a live drawing. Undo afterwards.',
            0, 'Run it', 'Cancel', '', '') != 1:
        return 'cancelled', None

    log = ['CREATION PROBE', '']
    log.append('Layer: {}'.format(vs.GetLName(vs.ActLayer())))
    log.append('')

    log.append('1. Device with sockets (source)')
    first, first_sockets = probe_make_device(
        PROBE_PREFIX + ' A', 0, 0, 2.0, 1.0,
        [('skt_R', 'OUT 1', 'OUT', 0.5)], log)
    log.append('')

    log.append('2. Device with sockets (destination)')
    second, second_sockets = probe_make_device(
        PROBE_PREFIX + ' B', 6.0, 0, 2.0, 1.0,
        [('skt_L', 'IN 1', 'IN', 0.5)], log)
    log.append('')

    log.append('3. Wiring them with ConnectSelected')
    wired = False
    if first and second:
        wired = probe_connect(first, second, log)
    else:
        log.append('  skipped - a device was not created')
    log.append('')

    # Every step has to have worked. Wiring alone is not enough: a device
    # that came back without its sockets is a failure however the circuit read.
    devices_ok = bool(first and second)
    sockets_ok = first_sockets and second_sockets
    if devices_ok and sockets_ok and wired:
        verdict = 'Generation is possible: devices, sockets and wiring all worked.'
    else:
        missing = []
        if not devices_ok:
            missing.append('devices')
        if not sockets_ok:
            missing.append('sockets')
        if not wired:
            missing.append('wiring')
        verdict = ('Generation is NOT possible as designed - {} failed. '
                   'See the log.'.format(' and '.join(missing)))
    log.append(verdict)
    log.append('')
    log.append('Undo now to remove the probe objects.')

    path = save_text('creation_probe', '\n'.join(report_header('CREATION PROBE')
                                                 + log))
    vs.AlrtDialog('{}\n\nFull log:\n{}'.format(verdict, path))
    return 'done', '{}\n{}'.format(verdict, path)


# ═══════════════════════════════════════════════════════════════════════════
# CLAUDE API CLIENT
# ═══════════════════════════════════════════════════════════════════════════
#
# Raw HTTPS rather than the official `anthropic` SDK, deliberately: this whole
# plug-in is one file pasted into the Plug-in Manager, and Vectorworks' embedded
# Python has no install step a user could run. Adding a pip dependency would
# trade the entire install story for a nicer client object.
#
# Vectorworks 2026 ships Python 3.9 with _ssl, _socket, urllib, json AND
# certifi in site-packages, so certificate verification works without bundling
# anything.
#
# EVERY call is logged to claude_usage.csv with its real token counts and
# computed cost. Estimates made before a run are guesses; this records what was
# actually billed.
#
# A key is OPTIONAL. Nothing here is consulted unless a Claude-powered feature
# is chosen, and the four local tools never touch it -- so the plug-in installs
# and runs fully offline. There is no shared key: each person who installs
# this supplies their own, which is why one must never reach the repository.

CLAUDE_CONFIG_FILE = 'claude_config.json'
CLAUDE_USAGE_FILE = 'claude_usage.csv'
CLAUDE_ENDPOINT = 'https://api.anthropic.com/v1/messages'
CLAUDE_API_VERSION = '2023-06-01'

# US dollars per MILLION tokens. Published rates as of 2026-06; they can change,
# so the log records the rate used rather than only the derived cost.
CLAUDE_RATES = {
    'claude-opus-5':    {'input': 5.00,  'output': 25.00},
    'claude-sonnet-5':  {'input': 2.00,  'output': 10.00},
    'claude-haiku-4-5': {'input': 1.00,  'output': 5.00},
}
CACHE_WRITE_MULTIPLIER = 1.25   # writing to cache costs more than plain input
CACHE_READ_MULTIPLIER = 0.10    # reading from cache costs a fraction

CLAUDE_DEFAULT_MODEL = 'claude-opus-5'
CLAUDE_CONFIG_TEMPLATE = {
    '_comment': 'CC Tools - Claude API settings. Your key is NOT part of your '
                'Claude subscription; create one at console.anthropic.com and '
                'load credits there. Keep this file private.',
    'api_key': '',
    'model': CLAUDE_DEFAULT_MODEL,
    'max_tokens': 16000,
}


def claude_config_path():
    return os.path.join(BASE_FOLDER, CLAUDE_CONFIG_FILE)


def ask_for_api_key(existing=None):
    """First-run prompt for the user's own API key. Returns a config, or None.

    Each person who installs this supplies their own key -- there is no shared
    one to distribute, and the repository must never contain one. The key is
    typed here, written to a file only this account can read, and never
    surfaced in a report, a log or an error message.

    Note the field shows the key as typed; Vectorworks' layout dialogs have no
    documented password-style entry."""
    entered = {}
    dlg = vs.CreateLayout('Claude API Key', False, 'Save',
                          'Skip - use local tools only')

    vs.CreateStaticText(
        dlg, cWhyTxt,
        'Only the Claude-powered features need a key. Dump Fields, Normalise\n'
        'Names, Match Names and Spell Check all work offline without one.\n\n'
        'The Claude API is billed SEPARATELY from a Claude subscription.\n'
        'Create a key at console.anthropic.com and add credit to it. Your\n'
        'key is stored on this machine only, readable only by you.', -1)
    vs.CreateStaticText(dlg, cKeyLbl, 'API key:', -1)
    vs.CreateEditText(dlg, cKeyField, existing or '', 52)
    vs.CreateStaticText(dlg, cModelLbl, 'Model:', -1)
    vs.CreatePullDownMenu(dlg, cModelPopup, 44)
    vs.CreateStaticText(
        dlg, cCostTxt,
        'Every call is logged with its real token counts and cost to\n'
        'claude_usage.csv in the CC Tools folder.', -1)

    vs.SetFirstLayoutItem(dlg, cWhyTxt)
    vs.SetBelowItem(dlg, cWhyTxt, cKeyLbl, 0, 8)
    vs.SetBelowItem(dlg, cKeyLbl, cKeyField, 0, 0)
    vs.SetBelowItem(dlg, cKeyField, cModelLbl, 0, 8)
    vs.SetBelowItem(dlg, cModelLbl, cModelPopup, 0, 0)
    vs.SetBelowItem(dlg, cModelPopup, cCostTxt, 0, 8)

    def handler(item, data):
        if item == kSetup:
            for index, (_model_id, label) in enumerate(CLAUDE_MODEL_CHOICES):
                vs.AddChoice(dlg, cModelPopup, label, index)
            vs.SelectChoice(dlg, cModelPopup, 0, True)
        elif item == kOK:
            entered['api_key'] = (vs.GetItemText(dlg, cKeyField) or '').strip()
            index = vs.GetSelectedChoiceIndex(dlg, cModelPopup, 0)
            if index < 0 or index >= len(CLAUDE_MODEL_CHOICES):
                index = 0
            entered['model'] = CLAUDE_MODEL_CHOICES[index][0]

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    if not entered.get('api_key'):
        return None
    entered['max_tokens'] = 16000
    return entered


def save_claude_config(config):
    """Write settings so only this account can read them.

    A plain file in Documents is not a secret store, but 0600 at least keeps it
    out of reach of other accounts on the machine. Anything stronger (Keychain)
    would mean shelling out, which is not something this plug-in should do."""
    import json
    import stat
    os.makedirs(BASE_FOLDER, exist_ok=True)
    path = claude_config_path()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'_comment': CLAUDE_CONFIG_TEMPLATE['_comment'],
                   'api_key': config['api_key'],
                   'model': config.get('model', CLAUDE_DEFAULT_MODEL),
                   'max_tokens': config.get('max_tokens', 16000)}, f, indent=2)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass          # best effort; the file is still written
    return path


def load_claude_config(prompt_if_missing=True):
    """Return (config, error), asking for a key on first run.

    Never logs or reports the key itself."""
    import json
    path = claude_config_path()
    config = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {}
    except Exception as err:
        return None, 'Could not read {}: {}'.format(CLAUDE_CONFIG_FILE, err)

    key = (config.get('api_key') or '').strip()
    if not key:
        if not prompt_if_missing:
            return None, 'No Claude API key configured.'
        entered = ask_for_api_key()
        if not entered:
            return None, ('No API key, so nothing was sent.\n\n'
                          'The other tools -- Dump Fields, Normalise Names,'
                          ' Match Names and Spell Check -- work without one.\n\n'
                          'API access is billed separately from a Claude '
                          'subscription -- create a key at '
                          'console.anthropic.com.')
        save_claude_config(entered)
        config = entered
        key = entered['api_key']

    config['api_key'] = key
    config.setdefault('model', CLAUDE_DEFAULT_MODEL)
    config.setdefault('max_tokens', 16000)
    return config, None


# ─── Usage accounting ────────────────────────────────────────────────────────
def usage_cost(model, usage):
    """Dollar cost of one call, from the token counts the API actually returned.

    Cache reads and writes are priced differently from plain input, so a run
    that looks cheap on input_tokens alone can be wrong either way."""
    rates = CLAUDE_RATES.get(model)
    if not rates:
        return None
    plain_in = usage.get('input_tokens', 0) or 0
    cache_write = usage.get('cache_creation_input_tokens', 0) or 0
    cache_read = usage.get('cache_read_input_tokens', 0) or 0
    out = usage.get('output_tokens', 0) or 0

    per_token_in = rates['input'] / 1000000.0
    per_token_out = rates['output'] / 1000000.0
    return (plain_in * per_token_in
            + cache_write * per_token_in * CACHE_WRITE_MULTIPLIER
            + cache_read * per_token_in * CACHE_READ_MULTIPLIER
            + out * per_token_out)


def log_claude_usage(model, purpose, usage, cost, note=''):
    """Append one row per call. This file is the record of real spend."""
    os.makedirs(BASE_FOLDER, exist_ok=True)
    path = os.path.join(BASE_FOLDER, CLAUDE_USAGE_FILE)
    new = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(['When', 'File', 'Purpose', 'Model', 'Input tokens',
                             'Cache write', 'Cache read', 'Output tokens',
                             'Cost USD', 'Input $/Mtok', 'Output $/Mtok', 'Note'])
        rates = CLAUDE_RATES.get(model, {})
        writer.writerow([
            time.strftime('%Y-%m-%d %H:%M:%S'), vs.GetFName(), purpose, model,
            usage.get('input_tokens', 0),
            usage.get('cache_creation_input_tokens', 0),
            usage.get('cache_read_input_tokens', 0),
            usage.get('output_tokens', 0),
            '' if cost is None else '{:.4f}'.format(cost),
            rates.get('input', ''), rates.get('output', ''), note,
        ])
    return path


def usage_totals():
    """Everything spent so far, read back from the log. Returns (calls, dollars)."""
    path = os.path.join(BASE_FOLDER, CLAUDE_USAGE_FILE)
    calls = 0
    total = 0.0
    try:
        with open(path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header or 'Cost USD' not in header:
                return 0, 0.0
            cost_i = header.index('Cost USD')
            for row in reader:
                if len(row) <= cost_i:
                    continue
                calls += 1
                try:
                    total += float(row[cost_i])
                except (ValueError, TypeError):
                    pass
    except FileNotFoundError:
        return 0, 0.0
    except Exception:
        return calls, total
    return calls, total


# ─── The call itself ─────────────────────────────────────────────────────────
def claude_request(config, messages, system=None, purpose='request',
                   max_tokens=None, note=''):
    """POST to the Messages API. Returns (reply_text, usage, cost, error).

    On any failure the error string is safe to show: it never contains the key.
    Usage is logged even for calls that fail partway, because a request that
    errored after the model produced tokens is still billed."""
    import json
    import urllib.request
    import urllib.error

    model = config.get('model', CLAUDE_DEFAULT_MODEL)
    body = {
        'model': model,
        'max_tokens': max_tokens or config.get('max_tokens', 16000),
        'messages': messages,
    }
    if system:
        body['system'] = system

    payload = json.dumps(body).encode('utf-8')
    request = urllib.request.Request(CLAUDE_ENDPOINT, data=payload, method='POST')
    request.add_header('content-type', 'application/json')
    request.add_header('anthropic-version', CLAUDE_API_VERSION)
    request.add_header('x-api-key', config['api_key'])

    context = None
    try:
        import ssl
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            context = ssl.create_default_context()
    except Exception:
        context = None

    try:
        opened = urllib.request.urlopen(request, timeout=600, context=context)
        raw = opened.read().decode('utf-8')
    except urllib.error.HTTPError as err:
        detail = ''
        try:
            detail = json.loads(err.read().decode('utf-8')).get(
                'error', {}).get('message', '')
        except Exception:
            pass
        hint = ''
        if err.code == 401:
            hint = ('\n\nThe key in {} was rejected. API access is separate '
                    'from a Claude subscription -- the key must come from '
                    'console.anthropic.com with credit on it.'.format(
                        CLAUDE_CONFIG_FILE))
        elif err.code == 429:
            hint = '\n\nRate limited or out of credit. Wait, or top up.'
        return None, {}, None, 'Claude API error {}: {}{}'.format(
            err.code, detail or err.reason, hint)
    except Exception as err:
        return None, {}, None, 'Could not reach the Claude API: {}'.format(err)

    try:
        data = json.loads(raw)
    except Exception as err:
        return None, {}, None, 'Unreadable reply from the Claude API: {}'.format(err)

    usage = data.get('usage', {}) or {}
    cost = usage_cost(model, usage)
    log_claude_usage(model, purpose, usage, cost, note)

    if data.get('stop_reason') == 'refusal':
        return None, usage, cost, 'Claude declined this request.'

    reply = ''.join(block.get('text', '') for block in data.get('content', [])
                    if block.get('type') == 'text')
    if not reply:
        return None, usage, cost, 'Claude returned no text.'
    return reply, usage, cost, None


def format_usage(usage, cost):
    """One readable line about what a call cost."""
    parts = ['{} in'.format(usage.get('input_tokens', 0))]
    if usage.get('cache_read_input_tokens'):
        parts.append('{} cached'.format(usage['cache_read_input_tokens']))
    parts.append('{} out'.format(usage.get('output_tokens', 0)))
    line = ', '.join(parts)
    if cost is not None:
        line += '  =  ${:.4f}'.format(cost)
    return line


# ═══════════════════════════════════════════════════════════════════════════
# LAUNCHER
# ═══════════════════════════════════════════════════════════════════════════
lToolLbl = 304
lDumpChk, lNormChk, lMatchChk, lSpellChk = 305, 306, 307, 310
lRefChk = 311
lProbeChk = 312
lOrderTxt, lHintTxt = 308, 309


def ask_which_tools():
    """Pick one or more tools. Returns a list of TOOL_* constants, or None.

    The list comes back in RUN order, not tick order -- see run_cc_tools."""
    chosen = {}
    dlg = vs.CreateLayout('CC Tools', False, 'Continue', 'Cancel')

    vs.CreateStaticText(dlg, lToolLbl, 'Run:', -1)
    vs.CreateCheckBox(dlg, lDumpChk, 'Dump Fields  (diagnostic, read-only)')
    vs.CreateCheckBox(dlg, lNormChk, 'Normalise Names  (uppercase / trim)')
    vs.CreateCheckBox(dlg, lMatchChk, 'Match Names and Display Tags')
    vs.CreateCheckBox(dlg, lSpellChk, 'Spell Check')
    vs.CreateCheckBox(dlg, lRefChk, 'Export Reference Schematic')
    vs.CreateCheckBox(dlg, lProbeChk, 'Creation Probe  (writes - scratch file only)')
    vs.CreateStaticText(
        dlg, lOrderTxt,
        'Run in this order. Normalising first resolves case- and space-only\n'
        'mismatches, so Match only asks about genuinely different pairs, and\n'
        'Spell Check then sees the settled spelling of every name.', -1)
    vs.CreateStaticText(
        dlg, lHintTxt, 'Reports are written to ~/Documents/CC Tools/', -1)

    vs.SetFirstLayoutItem(dlg, lToolLbl)
    vs.SetBelowItem(dlg, lToolLbl, lDumpChk, 0, 0)
    vs.SetBelowItem(dlg, lDumpChk, lNormChk, 0, 0)
    vs.SetBelowItem(dlg, lNormChk, lMatchChk, 0, 0)
    vs.SetBelowItem(dlg, lMatchChk, lSpellChk, 0, 0)
    vs.SetBelowItem(dlg, lSpellChk, lRefChk, 0, 0)
    vs.SetBelowItem(dlg, lRefChk, lProbeChk, 0, 0)
    vs.SetBelowItem(dlg, lProbeChk, lOrderTxt, 0, 8)
    vs.SetBelowItem(dlg, lOrderTxt, lHintTxt, 0, 8)

    def handler(item, data):
        if item == kSetup:
            # Nothing ticked by default. These edit a live drawing, so the
            # user should have to choose a tool rather than find one already
            # chosen for them.
            vs.SetBooleanItem(dlg, lDumpChk, False)
            vs.SetBooleanItem(dlg, lNormChk, False)
            vs.SetBooleanItem(dlg, lMatchChk, False)
            vs.SetBooleanItem(dlg, lSpellChk, False)
            vs.SetBooleanItem(dlg, lRefChk, False)
            vs.SetBooleanItem(dlg, lProbeChk, False)
        elif item == kOK:
            picked = []
            # Fixed order, independent of which boxes the user ticked first.
            if vs.GetBooleanItem(dlg, lDumpChk):
                picked.append(TOOL_DUMP)
            if vs.GetBooleanItem(dlg, lNormChk):
                picked.append(TOOL_NORMALISE)
            if vs.GetBooleanItem(dlg, lMatchChk):
                picked.append(TOOL_MATCH)
            if vs.GetBooleanItem(dlg, lSpellChk):
                picked.append(TOOL_SPELL)
            if vs.GetBooleanItem(dlg, lRefChk):
                picked.append(TOOL_REFERENCE)
            if vs.GetBooleanItem(dlg, lProbeChk):
                picked.append(TOOL_PROBE)
            chosen['tools'] = picked

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    return chosen.get('tools')


TOOL_RUNNERS = [
    (TOOL_DUMP, 'Dump Fields'),
    (TOOL_NORMALISE, 'Normalise Names'),
    (TOOL_MATCH, 'Match Names and Tags'),
    (TOOL_SPELL, 'Spell Check'),
    (TOOL_REFERENCE, 'Export Reference Schematic'),
    (TOOL_PROBE, 'Creation Probe'),
]


def run_cc_tools():
    """Run every selected tool in sequence, then report once.

    Each tool returns (status, summary):
      'done'      -- finished; carry on to the next tool
      'cancelled' -- the user backed out of that tool's dialog; skip to the next
      'stopped'   -- the tool refused to proceed (collision, unresolved field,
                     mid-run error). The chain HALTS: whatever tripped it needs
                     looking at before another tool touches the same drawing.
    """
    tools = ask_which_tools()
    if tools is None:
        return
    if not tools:
        vs.AlrtDialog('No tools selected.')
        return

    runners = {
        TOOL_DUMP: tool_dump_fields,
        TOOL_NORMALISE: tool_normalise,
        TOOL_MATCH: tool_match_names_and_tags,
        TOOL_SPELL: tool_spellcheck,
        TOOL_REFERENCE: tool_export_reference,
        TOOL_PROBE: tool_creation_probe,
    }
    names = dict((tool, name) for tool, name in TOOL_RUNNERS)

    summaries = []
    note = ''
    for idx, tool in enumerate(tools):
        status, summary = runners[tool]()
        if summary:
            summaries.append('{}: {}'.format(names[tool], summary))
        elif status == 'cancelled':
            summaries.append('{}: cancelled'.format(names[tool]))

        if status == 'stopped':
            # The tool already explained itself in its own alert; here we only
            # account for what never got to run.
            skipped = [names[t] for t in tools[idx + 1:]]
            note = '\n\nStopped at {}.'.format(names[tool])
            if skipped:
                note += ' Not run: {}.'.format(', '.join(skipped))
            break

    if summaries or note:
        vs.AlrtDialog('\n\n'.join(summaries) + note)


run_cc_tools()
