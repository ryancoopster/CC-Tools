# CC Tools - a single ConnectCAD utility plug-in for Vectorworks 2026.
#
# ONE menu command. Running it opens a launcher offering three tools:
#   1. Dump Fields          - read-only diagnostic
#   2. Normalise Names      - UPPERCASE and/or trim names & tags
#   3. Match Names and Tags - reconcile Name vs Display Tag
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
    # Fields the caller is already rewriting. Without this the cascade
    # (equipment -> its device -> that device's equipment) re-plans the very
    # edit it started from, which dedupe would drop but the report would show.
    spoken_for = set((e['handle'], e['field']) for e in edits)

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
        for device_handle, edit in renamed_devices.items():
            partner = dev_to_equip.get(device_handle)
            if partner is None:
                continue
            field = resolve_field(partner, EQUIP_NAME_FIELDS)
            if not field or (partner, field) in spoken_for:
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
# LAUNCHER
# ═══════════════════════════════════════════════════════════════════════════
lToolLbl = 304
lDumpChk, lNormChk, lMatchChk = 305, 306, 307
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
    vs.CreateStaticText(
        dlg, lOrderTxt,
        'Run in this order. Normalising first resolves case- and space-only\n'
        'mismatches, so Match only asks about genuinely different pairs.', -1)
    vs.CreateStaticText(
        dlg, lHintTxt, 'Reports are written to ~/Documents/CC Tools/', -1)

    vs.SetFirstLayoutItem(dlg, lToolLbl)
    vs.SetBelowItem(dlg, lToolLbl, lDumpChk, 0, 0)
    vs.SetBelowItem(dlg, lDumpChk, lNormChk, 0, 0)
    vs.SetBelowItem(dlg, lNormChk, lMatchChk, 0, 0)
    vs.SetBelowItem(dlg, lMatchChk, lOrderTxt, 0, 8)
    vs.SetBelowItem(dlg, lOrderTxt, lHintTxt, 0, 8)

    def handler(item, data):
        if item == kSetup:
            vs.SetBooleanItem(dlg, lDumpChk, False)
            vs.SetBooleanItem(dlg, lNormChk, True)
            vs.SetBooleanItem(dlg, lMatchChk, False)
        elif item == kOK:
            picked = []
            # Fixed order, independent of which boxes the user ticked first.
            if vs.GetBooleanItem(dlg, lDumpChk):
                picked.append(TOOL_DUMP)
            if vs.GetBooleanItem(dlg, lNormChk):
                picked.append(TOOL_NORMALISE)
            if vs.GetBooleanItem(dlg, lMatchChk):
                picked.append(TOOL_MATCH)
            chosen['tools'] = picked

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    return chosen.get('tools')


TOOL_RUNNERS = [
    (TOOL_DUMP, 'Dump Fields'),
    (TOOL_NORMALISE, 'Normalise Names'),
    (TOOL_MATCH, 'Match Names and Tags'),
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
