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
TOOL_PROMPT    = 6
TOOL_JOB       = 7
TOOL_PREFS     = 8
TOOL_SEARCH    = 9
TOOL_REPLACE   = 10

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
    """(owning device identifier, old socket name) -> new socket name.

    Socket names are only unique within their parent device, so the device has
    to be part of the key -- 'LAN_IN 1' exists on almost every speaker.

    Keyed on the device's NAME **and** its TAG, both. A PanelConnector's
    ConnectedDev holds one of the two, and in a drawing where they have drifted
    apart -- which is common enough that a whole tool exists to reconcile them
    -- keying on the name alone silently fails to match, and the connector
    keeps pointing at a socket name that no longer exists."""
    out = {}
    for e in edits:
        if e['kind'] != 'socket' or not e['is_link_name']:
            continue
        if is_unnamed(e['old']) or is_unnamed(e['new']):
            continue
        device = owning_device(e['handle'], parents)
        if device is None:
            continue
        for candidates in (DEVICE_NAME_FIELDS, DEVICE_TAG_FIELDS):
            field = resolve_field(device, candidates)
            identifier = read_field(device, field) if field else ''
            if not is_unnamed(identifier):
                out[(identifier, e['old'])] = e['new']
    return out


def unsynced_socket_references(edits, sync_edits):
    """Panel connectors still pointing at a socket name this run renamed.

    A socket rename reaches PanelConnector.ConnectedSkt only when the
    connector's ConnectedDev matches the socket's owning device. When it does
    not, nothing happens and nothing is said -- so this goes looking, and the
    report names every connector left behind."""
    renamed = set(e['old'] for e in edits
                  if e['kind'] == 'socket' and e['is_link_name']
                  and not is_unnamed(e['old']))
    if not renamed:
        return []
    handled = set(e['handle'] for e in sync_edits
                  if e['kind'] == 'panelconnector')

    stranded = []
    for handle in walk_document():
        if classify(handle) != 'panelconnector' or handle in handled:
            continue
        skt_field = resolve_field(handle, PCONN_SOCKET_FIELDS)
        dev_field = resolve_field(handle, PCONN_DEVICE_FIELDS)
        socket_name = read_field(handle, skt_field) if skt_field else ''
        if socket_name in renamed:
            stranded.append((read_field(handle, dev_field) if dev_field else '',
                             socket_name))
    return stranded


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


def save_csv(prefix, rows):
    """Write rows to a timestamped CSV. Row 0 is the header.

    newline='' is required, not stylistic: without it csv writes \r\r\n on
    Windows and every other line of the file is blank."""
    os.makedirs(BASE_FOLDER, exist_ok=True)
    path = os.path.join(BASE_FOLDER, '{}_{}.csv'.format(
        prefix, time.strftime('%Y%m%d_%H%M%S')))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(rows)
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


# ─── Device symbols: ConnectCAD's own way of stamping out devices ────────────
#
# A ConnectCAD "device symbol" is a symbol definition holding one fully-built
# Device plug-in object, sockets already in its profile group. Placing one is
# how the Device tool's Standard Insertion works, and it is a faithful port of
# Utilities::PlaceObjectFromSymbol: find the Device inside the definition,
# duplicate it onto the layer, copy across any records the duplicate lacks,
# reset, position.
#
# This is worth far more than convenience. A device stamped from a symbol needs
# no layout at all -- no socket pitch, no body sizing, no header baseline --
# because the symbol already IS a correct device. And it matches house style by
# construction, since the symbol came from a device somebody drew by hand.
#
# Make one with: build a device the way you want it, then "Save as Symbol..."
# in its Object Info palette.

DEVICE_RECORD = 'Device'


def device_pio_in_symbol(symdef):
    """The Device plug-in object inside a symbol definition, or None."""
    if not symdef:
        return None
    try:
        handle = vs.FInSymDef(symdef)
    except Exception:
        return None
    guard = 0
    while handle and guard < 200:
        guard += 1
        try:
            if vs.GetTypeN(handle) == TYPE_PIO and classify(handle) == 'device':
                return handle
        except Exception:
            pass
        handle = vs.NextObj(handle)
    return None


# ConnectCAD files device symbols it builds from the database into a symbol
# folder of this name. The root of the Resource Manager holds device PARTS --
# jacks, terminals, patch points -- which are also Device plug-in objects, so
# searching the root alone finds the wrong things and misses the right ones.
DEVICE_SYMBOL_FOLDERS = ['zConnectCAD db Created', 'ConnectCAD Devices', '']


def symbols_in_folder(folder):
    """Every symbol definition in one document symbol folder.

    Returns a list of (name, handle). An empty folder name means the root."""
    found = []
    try:
        list_id, count = vs.BuildResourceList(TYPE_SYMDEF, 0, folder)
    except Exception:
        return found
    for index in range(1, (count or 0) + 1):
        try:
            name = vs.GetNameFromResourceList(list_id, index)
            handle = vs.GetResourceFromList(list_id, index)
        except Exception:
            continue
        if handle:
            found.append((name, handle))
    return found


def device_symbol_catalogue(folders=None):
    """Every device symbol available, with what it is a device OF.

    Searches ConnectCAD's own device-symbol folder first. The Resource
    Manager root holds device PARTS -- jacks, terminals, patch points -- which
    are Device plug-in objects too, so a root-only search returns those and
    not the devices wanted here.

    Make and model are read from the Device inside each symbol rather than
    from its name: ConnectCAD names these Make_Model, but a drawing's own
    symbols may be named anything."""
    catalogue = []
    seen = set()
    for folder in (folders if folders is not None else DEVICE_SYMBOL_FOLDERS):
        for name, symdef in symbols_in_folder(folder):
            if name in seen:
                continue
            device = device_pio_in_symbol(symdef)
            if not device:
                continue
            seen.add(name)
            group = None
            try:
                group = vs.GetCustomObjectProfileGroup(device)
            except Exception:
                pass
            sockets = 0
            if group:
                handle = vs.FInGroup(group)
                guard = 0
                while handle and guard < 400:
                    guard += 1
                    if classify(handle) == 'socket':
                        sockets += 1
                    handle = vs.NextObj(handle)
            # The device's real height, so a section containing it can be
            # sized. A symbol device's height comes from the symbol, not from
            # the job's socket list -- which is usually empty for one, since
            # the whole point of a symbol is that its sockets are already
            # placed. Without this, sections stacked below it would overlap.
            height = 0.0
            box = bounds(device)
            if box:
                height = box[3] - box[1]

            catalogue.append({
                'symbol': name,
                'folder': folder or '(root)',
                'handle': symdef,
                'make': read_field(device, 'make'),
                'model': read_field(device, 'model'),
                'sockets': sockets,
                'height': height,
            })
    # A symbol that names what it is a device of is a real device; the parts
    # in the root generally do not. Sort those to the front.
    catalogue.sort(key=lambda e: (not (e['make'] or e['model']), e['symbol']))
    return catalogue


def normalise_model(value):
    """Compare makes and models forgivingly.

    The same product is written 'Galaxy 408', 'GALAXY-408' and 'Galaxy_408'
    across a drawing set, so matching has to ignore case, spaces, hyphens and
    underscores or it will miss symbols that are plainly there.
    """
    out = []
    for ch in (value or ''):
        if ch.isalnum():
            out.append(ch.lower())
    return ''.join(out)


def find_device_symbol(make, model, catalogue=None):
    """The device symbol for this make and model, or None.

    Make and model together are the identity; model alone is accepted as a
    fallback because a drawing often carries only one product of a given name,
    but a bare make is never enough to pick a device."""
    if catalogue is None:
        catalogue = device_symbol_catalogue()
    if not model:
        return None

    want_make = normalise_model(make)
    want_model = normalise_model(model)

    for entry in catalogue:
        if (normalise_model(entry['model']) == want_model
                and normalise_model(entry['make']) == want_make):
            return entry
    for entry in catalogue:
        if normalise_model(entry['model']) == want_model:
            return entry
    return None


def copy_missing_records(source, target):
    """Copy records the target lacks, as PlaceObjectFromSymbol does.

    A device symbol can carry records attached to the definition rather than to
    the Device inside it; without this they are lost on placement."""
    copied = 0
    try:
        have = set()
        for i in range(1, (vs.NumRecords(target) or 0) + 1):
            record = vs.GetRecord(target, i)
            if record:
                have.add(vs.GetName(record))
        for i in range(1, (vs.NumRecords(source) or 0) + 1):
            record = vs.GetRecord(source, i)
            if not record:
                continue
            name = vs.GetName(record)
            if not name or name in have:
                continue
            vs.SetRecord(target, name)
            for f in range(1, (vs.NumFields(record) or 0) + 1):
                field = vs.GetFldName(record, f)
                if field:
                    vs.SetRField(target, name, field,
                                 vs.GetRField(source, name, field))
            copied += 1
    except Exception:
        pass
    return copied


def place_device_from_symbol(symdef, x, y, name=None, tag=None):
    """Stamp a device out of a device symbol. Returns the handle, or None.

    Port of Utilities::PlaceObjectFromSymbol. No layout is computed: the
    symbol's Device already has its sockets placed, so nothing here needs to
    know about grids, pitches or header baselines."""
    prototype = device_pio_in_symbol(symdef)
    if not prototype:
        return None
    try:
        device = vs.CreateDuplicateObject(prototype, vs.ActLayer())
    except Exception:
        return None
    if not device:
        return None

    copy_missing_records(symdef, device)

    # Move it into place from wherever the duplicate landed. (x, y) puts the
    # device's TOP EDGE at y and centres it on x, so a row of devices lines up
    # along its tops however tall each one is.
    box = bounds(device)
    if box:
        centre_x = (box[0] + box[2]) / 2.0
        try:
            vs.HMove(device, x - centre_x, y - box[3])
        except Exception:
            pass

    # Names are link keys, so set them last and reset once afterwards.
    if name is not None:
        write_field(device, resolve_field(device, DEVICE_NAME_FIELDS) or 'name', name)
    if tag is not None:
        write_field(device, resolve_field(device, DEVICE_TAG_FIELDS) or 'tag', tag)
    try:
        vs.ResetObject(device)
    except Exception:
        pass
    return device


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

    if settings['action'] == ACTION_SPELL_APPLY:
        # This has to be handled explicitly. Falling through to the else below
        # would silently run "fix every suspect without asking" instead -- a
        # very different and far more destructive operation than applying a
        # sheet the user edited by hand.
        token_map, phrase_map, error = load_vocabulary_csv()
        if error:
            vs.AlrtDialog('Cannot apply replacements:\n\n{}'.format(error))
            return 'stopped', None
        if not token_map and not phrase_map:
            vs.AlrtDialog('No replacements found in {}.\n\nType them into the '
                          '"Replace with" column and save the file.'.format(
                              VOCAB_FILE))
            return 'done', 'nothing to apply from {}'.format(VOCAB_FILE)
        return apply_corrections(handles, token_map, phrase_map, [], settings,
                                 source=VOCAB_FILE)

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


def object_class(handle):
    """An object's class name, or '' if it cannot be read.

    Worth exporting: ConnectCAD files circuits by signal into
    CC-Circuit-Signal-<SIGNAL>, and those classes are how a schematic gets
    divided across sheets. A reference export without them cannot show how a
    drawing is organised."""
    try:
        return vs.GetClass(handle) or ''
    except Exception:
        return ''


# EquipItem carries a device's PHYSICAL properties -- the ones the schematic
# object does not. Exporting them lets the curated device list be seeded from a
# drawing rather than typed: ConnectCAD's shipped database knew only 2 of the
# 28 devices in this drawing, so the rack layout is the better source.
EQUIP_PHYSICAL_FIELDS = {
    'width': 'Width', 'height': 'Height', 'depth': 'Depth',
    'weight': 'weight', 'power': 'power',
    'rack_width': 'width_R', 'rack_u': 'heightU', 'mount': 'mount',
}


def equipment_physical(handle):
    """An equipment item's physical properties, blank ones omitted."""
    out = {}
    for key, field in EQUIP_PHYSICAL_FIELDS.items():
        resolved = resolve_field(handle, [field])
        value = read_field(handle, resolved) if resolved else ''
        value = (value or '').strip()
        if value and value not in ('0', '---'):
            out[key] = value
    return out


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
            'class': object_class(h),
            'sockets': device_local_sockets(h),
        })
        # Position matters as much as topology here. ConnectCAD wires by
        # horizontal alignment, and these drawings divide one layer into bands
        # by signal type -- neither is visible in a list of devices and
        # circuits, so an export without coordinates teaches what connects to
        # what but not how a schematic is actually arranged.
        box = bounds(h)
        if box:
            devices[-1]['x'] = round((box[0] + box[2]) / 2.0, 4)
            devices[-1]['y'] = round(box[3], 4)      # the top edge, as jobs use

    # Equipment items, keyed by make/model, so the export can seed the curated
    # device list with real dimensions, weights and rack heights.
    #
    # Scanned across the WHOLE DOCUMENT even when the export is scoped to one
    # layer. Equipment items live on rack layers while the devices being
    # exported live on a schematic layer, so a layer-scoped walk finds none of
    # them -- which is exactly what happened the first time this ran. The same
    # reasoning as the link-sync scan: the scope says which devices to write
    # out, not where their physical data is allowed to live.
    equipment = {}
    for h in walk_document():
        if classify(h) != 'equipment':
            continue
        make = read_field(h, 'make').strip()
        model = read_field(h, 'model').strip()
        if not make and not model:
            continue
        physical = equipment_physical(h)
        if physical:
            equipment.setdefault('{} | {}'.format(make, model), physical)

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
            # The human-readable name drawn along the middle of the line, and
            # the routing style. Both are house convention, which is the whole
            # point of exporting a reference.
            'cable': read_field(h, CIRCUIT_CABLE_FIELD),
            'line_mode': read_field(h, CIRCUIT_TYPE_FIELD),
            'class': object_class(h),
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
        # Physical properties from the rack layout, for seeding devices.md.
        'equipment': equipment,
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
TYPE_RECT = 3                 # the body rectangle handed to CC_DeviceFromShape
TYPE_SYMBOL = 15              # the label symbol ConnectCAD draws as the header
DEFAULTS_FOLDER = 14          # BuildResourceList: Defaults folder

# ConnectCAD's own socket layout, which is not hard-coded geometry: every
# distance is the SCHEMATIC GRID times an integer count from Device Builder
# preferences. Socket pitch is one grid unit; the first socket sits
# (top space + 1) units below the insertion point, two with stock preferences.
#
# On a 0.25" grid that is a 0.25" pitch and a 0.5" first drop -- exactly the
# convention these drawings use. Deriving it from the grid rather than hard-
# coding those inches means it stays right on a drawing gridded differently.
#
# Preference defaults, from CDeviceBuilderPrefs: minimum width 6 grid spaces,
# 1 space above, 0 below, 0 between socket groups. The block itself is
# serialised on the Device record format and is not reachable from script, so
# these are the stock values; a drawing whose Device Preferences differ needs
# them changed to match.
GRID_MIN_WIDTH_UNITS = 6
GRID_TOP_SPACE_UNITS = 1
GRID_BOTTOM_SPACE_UNITS = 0
GRID_GROUP_GAP_UNITS = 0
GRID_FALLBACK = 0.25          # ConnectCAD seeds its own callers with a default

# Used only when the schematic grid cannot be read at all.
#
# The header is not part of the rectangle you hand to CC_DeviceFromShape.
# A 2.0 x 1.0 request came back as a body spanning local y -1.000..0.400: the
# requested 1.0 became the body proper at -1.0..0.0, and ConnectCAD added a
# 0.4-tall header above it. So local y = 0 is the header's bottom edge, and
# that -- not the top of the whole block -- is what sockets hang from.
#
# These are inches ON THE PRINTED SHEET. Design-layer geometry is stored at
# world size and the layer scale maps it to paper, so a schematic at 1:2 needs
# twice the drawing distance to print the same gap. Ignoring that makes the
# spacing wrong by exactly the scale factor -- which looks like a placement
# bug and is not one.
SOCKET_FIRST_DROP_IN = 0.5
SOCKET_PITCH_IN = 0.25

# Clear space below the last socket, so it sits inside the block rather than on
# its edge. Mirrors the drop above the first one; adjust if the drawings say
# otherwise.
SOCKET_BOTTOM_MARGIN_IN = 0.5
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


# The Device record carries the physical properties itself -- it is not only
# EquipItem that has them. Confirmed from a real drawing's field dump:
#   width / height / depth   in DOCUMENT units, so inches must be scaled
#   weight / power           bare numbers, kilograms and watts
#   width_R                  'full-rack' | 'half-rack' | 'non-rack'
#   heightU                  size in rack units
# A generated device left these at zero reports no weight and no power in any
# schedule taken off the drawing, which is worse than useless -- it is a
# schedule that looks complete and is wrong.
DEVICE_PHYSICAL_FIELDS = (
    ('width', 'width', 'length'),
    ('height', 'height', 'length'),
    ('depth', 'depth', 'length'),
    ('weight', 'weight', 'number'),
    ('power', 'power', 'number'),
)


MM_TO_INCHES = 1.0 / 25.4
RACK_UNIT_INCHES = 1.75


def golden_physical(entry):
    """A curated device's physical properties, normalised. {} if unknown.

    Inches, kilograms and watts, whatever the file wrote them as."""
    if not entry:
        return {}
    out = {}
    for key in ('width', 'height', 'depth', 'weight', 'power'):
        value = golden_number(entry, key)
        if value is not None:
            out[key] = value
    racked = golden_is_rack_mounted(entry)
    if racked is not None:
        out['racked'] = racked
    rack_u = golden_number(entry, 'rack u')
    if rack_u is not None:
        out['rack_u'] = rack_u
    return out


def db_physical(entry):
    """The same, from ConnectCAD's shipped database. {} if it knows nothing.

    Its dimensions are MILLIMETRES; everything here is inches, so they are
    converted rather than written as-is into a field the drawing reads in its
    own units. Rack height is derived from the measured height because the
    database has no column for it -- that is arithmetic on real data, not a
    guess, and it is only done for something a rack width says is racked."""
    if not entry or not entry.get('rows'):
        return {}
    row = entry['rows'][0]

    def number(index):
        try:
            value = float((row[index] or '').strip())
        except (TypeError, ValueError, IndexError):
            return None
        return value if value else None

    out = {}
    for key, index in (('width', 2), ('height', 3), ('depth', 4)):
        value = number(index)
        if value:
            out[key] = value * MM_TO_INCHES
    for key, index in (('weight', 5), ('power', 6)):
        value = number(index)
        if value:
            out[key] = value
    # A 19" front panel is the tell for rack mounting; the database has no
    # flag of its own.
    if out.get('width') and 18.5 <= out['width'] <= 19.5:
        out['racked'] = True
        if out.get('height'):
            units = out['height'] / RACK_UNIT_INCHES
            if abs(units - round(units)) < 0.15 and round(units) >= 1:
                out['rack_u'] = float(round(units))
    return out


def apply_physical_properties(handle, physical, upi, log=None, source=''):
    """Write physical properties onto a Device. Returns the fields written.

    `physical` is the normalised dict from golden_physical or db_physical:
    inches, kilograms, watts. Lengths are scaled into the document's units on
    the way in.

    Anything unknown is left alone rather than written as zero. A blank field
    says "not recorded"; a zero says "weighs nothing", and a schedule taken off
    that looks complete and is wrong."""
    if not physical:
        return []
    written = []
    for prop, field, kind in DEVICE_PHYSICAL_FIELDS:
        value = physical.get(prop)
        if value is None:
            continue
        if kind == 'length':
            value = value * (upi or 1.0)
        if write_field(handle, field, '{:g}'.format(value)):
            written.append(field)

    if 'racked' in physical:
        if write_field(handle, 'width_R',
                       'full-rack' if physical['racked'] else 'non-rack'):
            written.append('width_R')
    if physical.get('rack_u') is not None:
        if write_field(handle, 'heightU', '{:g}'.format(physical['rack_u'])):
            written.append('heightU')

    if written and log is not None:
        log.append('          physical ({}): {}'.format(
            source or 'unknown source', ', '.join(written)))
    return written


def device_physical(make, model):
    """Physical properties for a make/model, and where they came from.

    The curated list first, because it is the house's own answer; ConnectCAD's
    shipped database second. Returns ({}, '') when neither knows the device --
    which is a thing worth SAYING, since a device with no dimensions is
    invisible to any schedule taken off the drawing."""
    physical = golden_physical(find_golden_device(make, model))
    if physical:
        return physical, 'curated list'
    physical = db_physical(find_db_device(make, model))
    if physical:
        return physical, 'device database'
    return {}, ''


def build_device(name, tag, make, model, x, y, socket_specs, log,
                 upi=1.0, scale=1.0, grid=None, description=''):
    """Build a device by hand, sockets and all. Returns (handle, sockets_ok).

    Used when no device symbol matches. Socket specs are
    (symbol, name, type, side) with optional signal and connector appended."""
    handle, ok = probe_make_device(name, x, y, 2.0, 1.0, socket_specs, log,
                                   upi, scale, grid, make, model)
    if handle:
        if tag and tag != name:
            write_field(handle, resolve_field(handle, DEVICE_TAG_FIELDS) or 'tag',
                        tag)
        if make:
            write_field(handle, 'make', make)
        if model:
            write_field(handle, 'model', model)
        # The drawing's own convention is Make_Model ('Meyer Sound_2100-LFC').
        # Without it the device label falls back to a generic word, which is
        # what every block in the first real job came out reading.
        if not description and (make or model):
            description = '{}_{}'.format(make, model).strip('_')
        if description:
            write_field(handle, 'description', description)
        physical, physical_source = device_physical(make, model)
        if physical:
            apply_physical_properties(handle, physical, upi, log,
                                      physical_source)
        elif make or model:
            # Said out loud. This used to be silent, so a run that wrote no
            # dimensions at all looked exactly like one that wrote them.
            log.append('          physical: nothing known for {} / {} -- add '
                       'it to the curated list'.format(make or '?', model or '?'))
        try:
            vs.ResetObject(handle)
        except Exception:
            pass
    return handle, ok


def probe_make_device(name, x, y, width, height, socket_specs, log,
                      upi=1.0, scale=1.0, grid=None, make='', model=''):
    """Create one device with sockets.

    Returns (device handle or None, every socket added). The second value
    matters: a device that comes back without its sockets is a failure, and
    reporting it as anything else would defeat the point of a probe."""
    # The rectangle becomes the body, so give it the height its sockets need
    # before ConnectCAD turns it into a device -- growing it afterwards would
    # move everything already placed against it.
    gx, gy = grid if grid else (None, None)
    height = body_height_for(socket_specs, upi, scale, gy)
    minimum = body_min_width(gx)
    if minimum > width:
        width = minimum
    log.append('  info  body         {:.3f} wide x {:.3f} tall for {} socket(s)'
               .format(width, height, len(socket_specs)))
    try:
        # (x, y) is the device's TOP edge, the same reference
        # place_device_from_symbol uses. Anchoring on the bottom instead would
        # make a device's header move as sockets were added to it, so two
        # devices written at the same y would not line up unless they happened
        # to have the same socket count.
        vs.Rect(x - width / 2.0, y, x + width / 2.0, y - height)
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

    # CC_DeviceFromShape DUPLICATES the shape into the device's profile group
    # and leaves the original on the layer. Without this the drawing fills up
    # with orphan rectangles sitting behind every device.
    try:
        vs.DelObject(rect)
        log.append('  ok    source rectangle removed')
    except Exception as err:
        log.append('  WARN  source rectangle left behind: {}'.format(err))

    # make/model are the CALLER'S. This used to hard-code 'CC Tools' / 'Probe'
    # -- the creation probe's own identity -- into every device a job built,
    # and a job that omitted either left the placeholder in the drawing.
    for field, value in (('name', name), ('tag', name),
                         ('make', make), ('model', model)):
        if value:
            write_field(device, field, value)
    log.append('  ok    name set{}'.format(
        ', make/model {} / {}'.format(make, model) if (make or model) else ''))

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

    # Measured once, before any socket is added, so a socket already placed
    # cannot enlarge the body the next one is measured against.
    body_box = body_bounds(group)
    if body_box:
        log.append('  info  body (local)   x {:.3f}..{:.3f}   y {:.3f}..{:.3f}'
                   .format(body_box[0], body_box[2], body_box[1], body_box[3]))
    else:
        log.append('  WARN  device body not measurable; sockets left unplaced')

    made = 0
    per_side = {}
    for spec in socket_specs:
        symbol_name, socket_name, socket_type, side = spec[:4]
        spec_signal = spec[4] if len(spec) > 4 else ''
        spec_connector = spec[5] if len(spec) > 5 else ''
        index = per_side.get(side, 0)
        per_side[side] = index + 1
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
        # ConnectCAD sizes the device itself and ignores the rectangle's
        # dimensions -- a 2.0 x 1.0 request came back 3.0 x 1.4 -- so the
        # socket is moved onto the device's MEASURED edge. Anything derived
        # from the requested width lands in the wrong place.
        place_socket(socket, body_box, side, index, upi, scale, gy)
        write_field(socket, 'name', socket_name)
        write_field(socket, 'tag', socket_name)
        write_field(socket, 'type', socket_type)
        # Without these the socket renders '???' for its signal and connector.
        write_field(socket, 'signal', spec_signal or 'LAN')
        write_field(socket, 'connector', spec_connector or 'EC-6A')
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

    header = header_bounds(group)
    rect = body_rect(group)
    if header and rect:
        rect_box = bounds(rect)
        if rect_box:
            header_width = header[2] - header[0]
            rect_width = rect_box[2] - rect_box[0]
            if abs(header_width - rect_width) > 0.001 and rect_width > 0:
                # The header is fixed width; the body is whatever rectangle
                # was handed in. Widen the body to match rather than leaving
                # a device whose two halves do not line up.
                factor = header_width / rect_width
                centre_x = (rect_box[0] + rect_box[2]) / 2.0
                centre_y = (rect_box[1] + rect_box[3]) / 2.0
                try:
                    vs.HScale2D(rect, centre_x, centre_y, factor, 1.0, False)
                    log.append('  ok    body widened {:.3f} -> {:.3f} to match '
                               'the header'.format(rect_width, header_width))
                    vs.ResetObject(device)
                except Exception as err:
                    log.append('  WARN  could not widen the body: {}'.format(err))
            else:
                log.append('  ok    body already matches the header width')

    log.extend(group_inventory(group, log_prefix='  '))
    log.extend(measure(device, group, log_prefix='  ', upi=upi, scale=scale))

    # The header sizes itself to the name; if it outgrows the body they no
    # longer line up. Report the difference rather than inferring it from a
    # screenshot.
    device_box = bounds(device)
    body = body_bounds(group)
    if device_box and body:
        header_width = device_box[2] - device_box[0]
        body_width = body[2] - body[0]
        log.append('  info  widths       device {:.3f}  body {:.3f}  '
                   'difference {:+.3f}'.format(header_width, body_width,
                                               header_width - body_width))
    return device, made == len(socket_specs)


MM_PER_INCH = 25.4
GETUNITS_UPI_INDEX = 3        # identified from a real document, see below


def units_per_inch():
    """How many document units make an inch, and how that was decided.

    GetUnits returns a tuple whose shape a real document settled:
        [0]=25  [1]=3  [2]=2  [3]=1.0  [4]='\"'  [5]=' sq ft'
    Index 3 is units-per-inch -- 1.0 alongside an inch unit mark. Taken by
    INDEX rather than by picking whichever value looks plausible, which is how
    25 was once mistaken for it and multiplied every distance by 25.

    Sanity-checked and defaulted to 1.0, since a wrong conversion here scales
    the whole drawing rather than failing visibly."""
    getter = getattr(vs, 'GetUnits', None)
    if getter is not None:
        try:
            result = getter()
        except Exception:
            result = None
        if isinstance(result, (list, tuple)) and len(result) > GETUNITS_UPI_INDEX:
            try:
                value = float(result[GETUNITS_UPI_INDEX])
            except (TypeError, ValueError):
                value = 0.0
            # 1 for inches, 25.4 for millimetres, 2.54 for centimetres.
            if 0.1 <= value <= 1000:
                return value, 'GetUnits()[{}] = {:g}'.format(
                    GETUNITS_UPI_INDEX, value)
    return 1.0, 'assuming 1 unit = 1 inch'


def raw_units_report():
    """Everything GetUnits returns, for identifying the units field for real.

    Reported rather than interpreted: one value in here is units-per-inch, but
    which one varies, and a wrong pick is invisible until every object is
    displaced by a constant factor."""
    getter = getattr(vs, 'GetUnits', None)
    if getter is None:
        return 'GetUnits unavailable'
    try:
        result = getter()
    except Exception as err:
        return 'GetUnits failed: {}'.format(err)
    if isinstance(result, (list, tuple)):
        return ', '.join('[{}]={!r}'.format(i, v) for i, v in enumerate(result))
    return repr(result)


def layer_scale(layer=None):
    """The active layer's scale, and how it was obtained.

    A scale of 48 means 1:48 -- 48 drawing units print as one inch. Returned
    as 1.0 when it cannot be read, which draws at world size rather than
    guessing a factor."""
    getter = getattr(vs, 'GetLScale', None)
    if getter is None:
        return 1.0, 'GetLScale unavailable; treating the layer as 1:1'
    try:
        value = float(getter(layer if layer is not None else vs.ActLayer()))
    except Exception as err:
        return 1.0, 'GetLScale failed ({}); treating the layer as 1:1'.format(err)
    if value <= 0:
        return 1.0, 'GetLScale returned {}; treating the layer as 1:1'.format(value)
    return value, '1:{:g}'.format(value)


def group_inventory(group, log_prefix='  '):
    """Every object in the profile group, with its record and bounds.

    The header and the body are both drawn by ConnectCAD and only one of them
    is the rectangle handed in, so which is which has to be read rather than
    assumed. This is how the width mismatch was found."""
    out = []
    if not group:
        return ['{}info  no profile group'.format(log_prefix)]
    handle = vs.FInGroup(group)
    guard = 0
    while handle and guard < 200:
        guard += 1
        record = get_pio_name(handle) or ''
        try:
            type_n = vs.GetTypeN(handle)
        except Exception:
            type_n = -1
        box = bounds(handle)
        if box:
            out.append('{}info  in group: type {:<3} {:<14} x {:.3f}..{:.3f}  '
                       'y {:.3f}..{:.3f}  (w {:.3f})'.format(
                           log_prefix, type_n, record or '-', box[0], box[2],
                           box[1], box[3], box[2] - box[0]))
        else:
            out.append('{}info  in group: type {:<3} {:<14} (no bounds)'.format(
                log_prefix, type_n, record or '-'))
        handle = vs.NextObj(handle)
    return out


def mm_to_units(millimetres, upi):
    """Convert a millimetre length into document units.

    Correct whatever the document works in: at 1 unit per inch a 6.35 mm grid
    becomes 0.25 units; at 25.4 units per inch it stays 6.35."""
    return millimetres * (upi or 1.0) / MM_PER_INCH


def schematic_grid(upi=1.0):
    """The schematic grid (gx, gy), and where it came from.

    ConnectCAD reads SchematicsGridX / SchematicsGridY off the 'ConnectCAD
    Settings...' record format and falls back to the document's own grid
    preferences (selectors 78 and 79). This follows the same order.

    THE VALUES ARE MILLIMETRES, whatever the document's units are: a 0.25"
    grid reads as 6.35. Using them as document units made every device 25
    times too big. They are converted here, and both figures are reported
    so the conversion is checkable rather than assumed."""
    record = 'ConnectCAD Settings...'
    try:
        handle = vs.GetObject(record)
    except Exception:
        handle = None
    if handle:
        try:
            gx = float(vs.GetRField(handle, record, 'SchematicsGridX'))
            gy = float(vs.GetRField(handle, record, 'SchematicsGridY'))
            if gx > 0 and gy > 0:
                return (mm_to_units(gx, upi), mm_to_units(gy, upi),
                        'ConnectCAD Settings record, {:g} x {:g} mm'.format(gx, gy))
        except (TypeError, ValueError, Exception):
            pass
    try:
        gx = float(vs.GetPrefReal(78))
        gy = float(vs.GetPrefReal(79))
        if gx > 0 and gy > 0:
            return (mm_to_units(gx, upi), mm_to_units(gy, upi),
                    'grid preferences 78/79, {:g} x {:g} mm'.format(gx, gy))
    except Exception:
        pass
    fallback = GRID_FALLBACK * upi
    return (fallback, fallback,
            'grid unreadable; assuming {}"'.format(GRID_FALLBACK))


def socket_drop(index, upi, scale=1.0, gy=None):
    """How far below the insertion point socket `index` sits.

    ConnectCAD's rule: one grid unit per socket, starting (top space + 1)
    units down. The inch constants are a fallback for when the grid cannot
    be read -- they encode the same thing for a 0.25" grid."""
    if gy and gy > 0:
        return ((GRID_TOP_SPACE_UNITS + 1) + index) * gy
    return (SOCKET_FIRST_DROP_IN + index * SOCKET_PITCH_IN) * upi * scale


def body_height_for(socket_specs, upi, scale, gy=None):
    """How tall the body must be to hold its sockets.

    ConnectCAD's rule, in grid units: one row per socket, plus the space
    above (top space + 1) and the space below. Left and right are independent
    stacks, so the deeper side decides.

    Falls back to the inch constants only when the grid cannot be read."""
    per_side = {}
    for spec in socket_specs:
        side = spec[3]
        per_side[side] = per_side.get(side, 0) + 1
    deepest = max(per_side.values()) if per_side else 1
    if gy and gy > 0:
        rows = (GRID_TOP_SPACE_UNITS + 1) + deepest + GRID_BOTTOM_SPACE_UNITS
        return rows * gy
    inches = (SOCKET_FIRST_DROP_IN + (deepest - 1) * SOCKET_PITCH_IN
              + SOCKET_BOTTOM_MARGIN_IN)
    return inches * upi * scale


def body_min_width(gx):
    """ConnectCAD's minimum device width: 6 grid spaces by default."""
    if gx and gx > 0:
        return GRID_MIN_WIDTH_UNITS * gx
    return 0.0


def header_bounds(group):
    """The label symbol's bounds -- the header strip at the top of a device.

    The header is a SYMBOL of fixed width, not text that grows with the name:
    a short name and a very long one produced identical 3.0-wide headers, the
    long one simply overflowing. So the body has to be drawn to the header's
    width, not the other way round."""
    if not group:
        return None
    handle = vs.FInGroup(group)
    guard = 0
    while handle and guard < 200:
        guard += 1
        try:
            if vs.GetTypeN(handle) == TYPE_SYMBOL:
                return bounds(handle)
        except Exception:
            pass
        handle = vs.NextObj(handle)
    return None


def body_rect(group):
    """The rectangle handed to CC_DeviceFromShape, which forms the body."""
    if not group:
        return None
    handle = vs.FInGroup(group)
    guard = 0
    while handle and guard < 200:
        guard += 1
        try:
            if vs.GetTypeN(handle) == TYPE_RECT:
                return handle
        except Exception:
            pass
        handle = vs.NextObj(handle)
    return None


def body_bounds(group):
    """The device body's bounds, in the frame its sockets actually live in.

    A socket sits inside the device's profile group, whose coordinates are
    device-LOCAL, while GetBBox on the device itself reports DOCUMENT
    coordinates. Mixing the two places a socket correctly only when the device
    happens to straddle the origin -- which is exactly what made one probe
    device look right and the other land far off to the side.

    Measuring the profile group's own geometry (everything in it that is not a
    socket) gives the body's extent in the same frame as the sockets, so no
    conversion is needed and none can be got wrong."""
    if not group:
        return None
    box = None
    handle = vs.FInGroup(group)
    guard = 0
    while handle and guard < 200:
        guard += 1
        if classify(handle) != 'socket':
            part = bounds(handle)
            if part:
                box = part if box is None else (
                    min(box[0], part[0]), min(box[1], part[1]),
                    max(box[2], part[2]), max(box[3], part[3]))
        handle = vs.NextObj(handle)
    return box


def header_baseline(body_box):
    """The y sockets hang from: the bottom of the device's header.

    In the profile group's local frame that is y = 0 -- the device's own
    origin, where ConnectCAD's header meets the body it was given. Measuring
    from the top of the block instead puts the whole stack a header's height
    too high, which is a constant error and so looks like a bad offset rather
    than a wrong reference point."""
    return 0.0


def insertion_point(handle):
    """An object's insertion point, or its bounding-box centre if unavailable.

    Sockets are symbols, and ConnectCAD places them by their INSERTION POINT:
    CreateSocketGroup calls PlaceObjectFromSymbol(name, pen), putting the
    socket's origin on the pen. Centring its bounding box instead offsets it
    by half the socket's width, so the connector straddles the device border
    rather than landing on it."""
    getter = getattr(vs, 'GetSymLoc', None)
    if getter is not None:
        try:
            point = getter(handle)
        except Exception:
            point = None
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                return float(point[0]), float(point[1])
            except (TypeError, ValueError):
                pass
    box = bounds(handle)
    if not box:
        return None
    return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0


def place_socket(socket, body_box, side, index, upi, scale=1.0, gy=None):
    """Move a socket onto the device body's edge at its place in the stack.

    Aligned by INSERTION POINT, not bounding-box centre, so the connector sits
    on the border the way ConnectCAD draws it rather than half in and half out.

    `body_box` must come from body_bounds -- the device's own bounds are in a
    different coordinate frame. `side` is -1 for the left edge, +1 for the
    right. `index` is the socket's position on that side, 0 upwards; sockets
    hang from the header on a fixed pitch rather than spreading across the
    block, so a device keeps its spacing however tall it is."""
    origin = insertion_point(socket)
    if not origin or not body_box:
        return False
    left, _bottom, right, _top = body_box
    target_x = right if side > 0 else left
    target_y = header_baseline(body_box) - socket_drop(index, upi, scale, gy)
    try:
        vs.HMove(socket, target_x - origin[0], target_y - origin[1])
        return True
    except Exception:
        return False


def bounds(handle):
    """(left, bottom, right, top) for an object, or None.

    GetBBox reports top before bottom and its tuple shape varies by build, so
    it is flattened and ordered here rather than at every call site."""
    try:
        raw = vs.GetBBox(handle)
    except Exception:
        return None
    flat = []
    for part in raw if isinstance(raw, (list, tuple)) else [raw]:
        if isinstance(part, (list, tuple)):
            flat.extend(part)
        else:
            flat.append(part)
    if len(flat) < 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in flat[:4])
    except (TypeError, ValueError):
        return None
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def measure(device, group, log_prefix='  ', upi=None, scale=1.0):
    """Report where the device and its sockets actually landed.

    Placement is the one thing the disassembly could not settle: the local
    frame's origin is documented, but where the label symbol sits relative to
    it is not. Measuring beats another round of guessing from a screenshot."""
    out = []
    if upi is None:
        upi = units_per_inch()[0]
    box = bounds(device)
    if box:
        out.append('{}info  device (doc)   x {:.3f}..{:.3f}   y {:.3f}..{:.3f}'
                   .format(log_prefix, box[0], box[2], box[1], box[3]))
    else:
        out.append('{}info  device bounds unavailable'.format(log_prefix))
    body = body_bounds(group)
    if body:
        out.append('{}info  body (local)   x {:.3f}..{:.3f}   y {:.3f}..{:.3f}'
                   .format(log_prefix, body[0], body[2], body[1], body[3]))
        out.append('{}info  header        {:.3f} units tall, sockets hang from '
                   'y {:.3f}'.format(log_prefix, body[3] - header_baseline(body),
                                     header_baseline(body)))

    handle = vs.FInGroup(group) if group else None
    guard = 0
    while handle and guard < 50:
        guard += 1
        if classify(handle) == 'socket':
            field = resolve_field(handle, SOCKET_NAME_FIELDS)
            name = read_field(handle, field) if field else '?'
            sbox = bounds(handle)
            if sbox and body:
                centre_y = (sbox[1] + sbox[3]) / 2.0
                drop_units = header_baseline(body) - centre_y
                divisor = (upi or 1.0) * (scale or 1.0)
                origin = insertion_point(handle)
                if origin:
                    edge = body[2] if origin[0] > 0 else body[0]
                    out.append('{}info  socket {:<8} origin {:+.4f} from the '
                               'border, {:.4f} below the header'.format(
                                   log_prefix, name, origin[0] - edge,
                                   header_baseline(body) - origin[1]))
                out.append('{}info  socket {:<8} edge x {:+.3f}   {:.4f} units = '
                           '{:.3f}" below the header'.format(
                               log_prefix, name,
                               (sbox[0] + sbox[2]) / 2.0 - (body[0] + body[2]) / 2.0,
                               drop_units, drop_units / divisor))
            elif sbox:
                out.append('{}info  socket {:<8} x {:.3f}..{:.3f}  y {:.3f}..{:.3f}'
                           .format(log_prefix, name, sbox[0], sbox[2],
                                   sbox[1], sbox[3]))
        handle = vs.NextObj(handle)
    return out


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


def active_layer_context(log):
    """Confirm where objects will land, and make the coordinate mode safe.

    Everything is drawn on the ACTIVE layer and sized against ITS scale, so
    both are reported before anything is created -- getting the wrong layer
    silently is the easiest way to produce objects at the wrong size in the
    wrong place.

    Absolute() matters because relative coordinate mode persists: if anything
    earlier in the session left it set, every Rect lands somewhere unintended."""
    layer = None
    try:
        layer = vs.ActLayer()
    except Exception:
        pass
    name = ''
    try:
        name = vs.GetLName(layer) if layer else ''
    except Exception:
        pass
    scale, scale_note = layer_scale(layer)
    upi, upi_note = units_per_inch()

    try:
        vs.Absolute()
    except Exception:
        pass

    log.append('Inserting on the ACTIVE layer: {}'.format(name or '(unnamed)'))
    log.append('  layer scale  {}'.format(scale_note))
    log.append('  units        {:.4f} unit(s) per inch  ({})'.format(upi, upi_note))
    log.append('  GetUnits()   {}'.format(raw_units_report()))
    gx, gy, grid_note = schematic_grid(upi)
    log.append('  grid         {:.4f} x {:.4f} drawing units  ({})'.format(
        gx, gy, grid_note))
    log.append('  spacing      {} grid unit(s) to the first socket, then 1 each'
               ' = {:.4f} / {:.4f} drawing units'.format(
                   GRID_TOP_SPACE_UNITS + 1, socket_drop(0, upi, scale, gy), gy))
    return layer, scale, upi, (gx, gy)


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
    # The active class and coordinate mode belong to the user; borrow and
    # return them rather than leaving the session changed.
    try:
        vs.PushAttrs()
    except Exception:
        pass
    _layer, scale, upi, grid = active_layer_context(log)
    log.append('')

    # A symbol beats hand-building: it already has its sockets, so none of the
    # grid or pitch rules below are consulted at all.
    catalogue = device_symbol_catalogue()
    log.append('Device symbols found: {}   (searched: {})'.format(
        len(catalogue), ', '.join(f or '(root)' for f in DEVICE_SYMBOL_FOLDERS)))
    for entry in catalogue[:15]:
        log.append('  {:<24} {:<22} {} {}  ({} socket(s))'.format(
            entry['symbol'][:24], entry['folder'][:22], entry['make'],
            entry['model'], entry['sockets']))
    if len(catalogue) > 15:
        log.append('  ... and {} more'.format(len(catalogue) - 15))
    if not catalogue:
        log.append('  none in this document, so devices are built by hand.')
        log.append('  To make one: build a device as you want it, then use')
        log.append('  "Save as Symbol..." in its Object Info palette.')
    log.append('')

    match = find_device_symbol('CC Tools', 'Probe', catalogue)
    if match:
        log.append('0. Stamping from the symbol {!r} -- no layout needed'.format(
            match['symbol']))
        stamped = place_device_from_symbol(
            match['handle'], 12.0, 0, PROBE_PREFIX + ' STAMPED',
            PROBE_PREFIX + ' STAMPED')
        if stamped:
            group = None
            try:
                group = vs.GetCustomObjectProfileGroup(stamped)
            except Exception:
                pass
            placed = 0
            handle = vs.FInGroup(group) if group else None
            guard = 0
            while handle and guard < 200:
                guard += 1
                if classify(handle) == 'socket':
                    placed += 1
                handle = vs.NextObj(handle)
            log.append('  ok    stamped with {} socket(s) already placed'.format(
                placed))
        else:
            log.append('  FAIL  could not stamp from the symbol')
        log.append('')

    log.append('1. Device with sockets (SHORT name, built by hand)')
    first, first_sockets = probe_make_device(
        PROBE_PREFIX + ' A', 0, 0, 2.0, 1.0,
        [('skt_R', 'OUT 1', 'OUT', 1),
         ('skt_R', 'OUT 2', 'OUT', 1),
         ('skt_R', 'OUT 3', 'OUT', 1)], log, upi, scale, grid,
        'CC Tools', 'Probe')
    log.append('')

    log.append('2. Device with sockets (LONG name -- does the header outgrow '
               'the body?)')
    second, second_sockets = probe_make_device(
        PROBE_PREFIX + ' B WITH A MUCH LONGER NAME', 6.0, 0, 2.0, 1.0,
        [('skt_L', 'IN 1', 'IN', -1),
         ('skt_L', 'IN 2', 'IN', -1),
         ('skt_L', 'IN 3', 'IN', -1)], log, upi, scale, grid,
        'CC Tools', 'Probe')
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
    if catalogue:
        log.append('')
        log.append('NOTE: {} device symbol(s) available. Stamping from a symbol '
                   'needs'.format(len(catalogue)))
        log.append('no layout at all and matches house style exactly, so the '
                   'hand-built')
        log.append('path above is only for devices that have no symbol yet.')
        log.append('')

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
    log.append('')
    log.append('Undo now to remove the probe objects.')

    try:
        vs.PopAttrs()
    except Exception:
        pass

    path = save_text('creation_probe', '\n'.join(report_header('CREATION PROBE')
                                                 + log))
    vs.AlrtDialog('{}\n\nFull log:\n{}'.format(verdict, path))
    return 'done', '{}\n{}'.format(verdict, path)


# ═══════════════════════════════════════════════════════════════════════════
# TOOL 7: SCHEMATIC JOBS  (export a prompt, then draw what comes back)
# ═══════════════════════════════════════════════════════════════════════════
#
# Two halves of one workflow, deliberately kept apart:
#
#   Export prompt   writes a profile of THIS drawing -- its conventions and a
#                   worked example -- to hand Claude alongside JOB-SPEC.md, so
#                   new work matches the document it is going into. Optional.
#   Draw job        asks for the file Claude produced and builds it.
#
# The file in between is the contract. It does not care whether the JSON came
# from a conversation in the Claude app, from an MCP server, or from anywhere
# else: the drawing step is identical either way. That is deliberate, and it is
# why this plug-in has no API client. One was written and never wired to
# anything, and deleting it lost nothing -- the route people actually use needs
# no key, no account and no billing.
#
# It also makes the whole thing reviewable. The job is a file you can read
# before a single object is created.

# ─── Drawing preferences ─────────────────────────────────────────────────────
#
# Generated objects used to take whatever the tool hard-coded. These are the
# choices that are genuinely the drawing's rather than the tool's, so they live
# in a file the user can edit and a dialog they can set.
#
# Kept as ONE flat JSON file rather than per-document settings because a job is
# often drawn into a fresh file: the conventions belong to the drafter, not to
# whichever document happens to be open.

PREFS_FILE = 'preferences.json'

# Every value the tool will read, with the value it uses when the file is
# missing, unreadable, or missing that key. The spacing figures are PRINTED
# INCHES and are scaled by the layer like everything else.
PREF_DEFAULTS = {
    'column_inches': 4.0,       # horizontal pitch between device columns
    'row_inches': 2.5,          # vertical pitch between device rows
    # 0 = sections sit flush, which is how these drawings are actually laid
    # out: contiguous regions of a dense field, with no space between them.
    'section_gap_inches': 0.0,  # blank space between sections
    'device_gap_inches': 0.5,   # blank space between stacked devices in a column
    'circuit_stagger_inches': 0.5,  # how far apart parallel circuit elbows sit; 0 = off
    'circuit_type': '',         # '' = leave ConnectCAD's own default alone
    'label_symbol': '',         # '' = leave ConnectCAD's own default alone
}

# Values ConnectCAD accepts for Circuit.CircuitType. There are exactly four,
# all lowercase, from a contiguous string run in the ConnectCAD binary bounded
# by a four-entry jump table in ConnectTool_EventSink::GetCircuitType:
#     polyline  rounded  chamfer  arrow
# 'direct' and 'orthogonal' were in this list once. They were guesses, they are
# not legal values, and ConnectCAD would have rejected them -- the same way the
# guessed field names once made these tools report success while changing
# nothing.
#
# 'arrow' is deliberately NOT offered. The first three share one computed route
# polygon and differ only in how corners are drawn, so switching between them
# is cosmetic. 'arrow' is a structurally different object -- paired stub arrows
# linked by __Arrow_ID and gated on __SameLayer -- so writing it onto an
# existing routed circuit does not convert it, it breaks it.
#
# '' means "leave whatever ConnectCAD set", the safe default for a field we did
# not choose. ConnectCAD's own default is 'polyline'; house style in these
# drawings is 'rounded' -- 370 circuits of 372.
CIRCUIT_TYPES = ['', 'rounded', 'polyline', 'chamfer']
CIRCUIT_TYPE_ARROW = 'arrow'

# Numeric preferences, with the range each is clamped to. A zero column pitch
# would stack every device in one place, and a huge one would scatter a job
# across a mile of drawing, so both ends are bounded.
PREF_RANGES = {
    'column_inches': (0.25, 240.0),
    'row_inches': (0.25, 240.0),
    'section_gap_inches': (0.0, 240.0),
    'device_gap_inches': (0.0, 240.0),
    'circuit_stagger_inches': (0.0, 48.0),
}


def prefs_path():
    return os.path.join(BASE_FOLDER, PREFS_FILE)


def load_prefs():
    """Read the preferences file, falling back to defaults per key.

    A corrupt or partial file must never stop the tool running: anything that
    will not parse, or any value out of range, silently reverts to the default
    for that key alone rather than discarding the whole file."""
    import json
    prefs = dict(PREF_DEFAULTS)
    try:
        with open(prefs_path(), 'r', encoding='utf-8') as f:
            stored = json.load(f)
    except Exception:
        return prefs
    if not isinstance(stored, dict):
        return prefs

    for key, default in PREF_DEFAULTS.items():
        if key not in stored:
            continue
        value = stored[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                continue
        elif isinstance(default, float):
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            low, high = PREF_RANGES.get(key, (None, None))
            if low is not None and not (low <= value <= high):
                continue
        elif not isinstance(value, str):
            continue
        prefs[key] = value
    return prefs


def save_prefs(prefs):
    """Write the preferences file. Returns the path, or None if it failed."""
    import json
    try:
        os.makedirs(BASE_FOLDER, exist_ok=True)
        with open(prefs_path(), 'w', encoding='utf-8') as f:
            json.dump(dict((k, prefs.get(k, v))
                           for k, v in PREF_DEFAULTS.items()), f, indent=2)
        return prefs_path()
    except Exception:
        return None


JOB_FILE = 'schematic_job.json'
PROMPT_FILE = 'schematic_prompt.txt'

# Devices are laid out on a column grid. ConnectCAD wires by horizontal
# alignment, so a schematic's layout IS its wiring -- devices that talk to each
# other belong in adjacent columns at compatible heights.
#
# These are the fallbacks used when preferences cannot be read; the live values
# come from load_prefs().
JOB_COLUMN_INCHES = PREF_DEFAULTS['column_inches']
JOB_ROW_INCHES = PREF_DEFAULTS['row_inches']


JOB_FORMAT = '''{
  "devices": [
    {
      "name": "SWTCH 4.01 HL UPPER",     // required, and the link key
      "tag": "SWTCH 4.01 HL UPPER",      // optional, defaults to name
      "make": "Luminex",                 // used to find a device symbol
      "model": "10i-IP",
      "column": 0,                       // 0 = leftmost
      "row": 0,                          // 0 = topmost
      "sockets": [                       // ignored when a symbol is found
        {"name": "LAN 1", "type": "OUT", "signal": "LAN",
         "connector": "EC-6A", "side": "R"}
      ]
    },
    {
      "name": "SPK 1.01 HL ARRAY 1",
      "make": "Meyer Sound", "model": "TIGRA-L",
      "column": 1,
      // Vertical position. ConnectCAD wires sockets that line up, so say
      // WHICH sockets should line up and let the plug-in do the arithmetic:
      "align_to": {"device": "SWTCH 4.01 HL UPPER",
                   "socket": "LAN 1", "my_socket": "LAN_IN 1"},
      "sockets": [
        {"name": "LAN_IN 1", "type": "IN", "signal": "LAN",
         "connector": "EC-6A", "side": "L"}
      ]
    }
  ],
  "circuits": [
    {"from": {"device": "SWTCH 4.01 HL UPPER", "socket": "LAN 1"},
     "to":   {"device": "SPK 1.01 HL ARRAY 1", "socket": "LAN_IN 1"},
     "signal": "MILAN PRI"}
  ]
}

Every circuit's destination needs an "align_to" back to its source, or the
devices are drawn but nothing is wired. A device fed from two sources can only
be aligned to one of them -- say so rather than leaving it silently unwired.'''


def job_path():
    return os.path.join(BASE_FOLDER, JOB_FILE)


def dialog_path(result):
    """The path out of a file-dialog result.

    VectorScript VAR parameters come back as Python return values, and the
    shape varies by routine and build: GetFileN returns (BOOLEAN, STRING),
    GetFile returns a lone STRING that some builds still wrap in a tuple. The
    last string in the result is the path in every one of those shapes."""
    if isinstance(result, (tuple, list)):
        for item in reversed(result):
            if isinstance(item, str):
                return item.strip()
        return ''
    return result.strip() if isinstance(result, str) else ''


def default_job_folder():
    """Where the file dialog should open.

    Claude hands the job over as a download, so the browser's folder is the
    likeliest place it is sitting."""
    downloads = os.path.expanduser('~/Downloads')
    if os.path.isdir(downloads):
        return downloads
    return BASE_FOLDER if os.path.isdir(BASE_FOLDER) else ''


def pick_job_file():
    """Ask for the job file with a Finder dialog. Returns (path, note).

    GetFileN is the GENERAL Open dialog:
        ok, path = vs.GetFileN(title, defaultFolder, mask)
    An empty mask accepts any file type. Vectorworks' own Marionette "Pick
    File" node calls it exactly that way (Libraries/Defaults/Marionette/File
    IO/Pick File.py), which is where the signature is confirmed from.

    It is registered by VS Shared Library.vwlibrary rather than by the main
    application binary, so it does NOT appear in the routine-name table inside
    the Vectorworks executable. Enumerating that table alone says the routine
    does not exist, which is how this code first ended up on GetFile.

    GetFile is the SCRIPT open dialog. Its file-type popup is hard-limited to
    *.txt, *.vss, *.xxt, *.vs, *.py, *.pyc, *.mpc with no "All Files" entry, so
    it CANNOT select a .json -- confirmed against the running application. It
    stays only as a fallback: a job saved as .txt still reads fine, because
    nothing here cares about the extension, only the contents."""
    start = default_job_folder()

    chooser = getattr(vs, 'GetFileN', None)
    if chooser is not None:
        try:
            path = dialog_path(chooser('Choose the job file', start, ''))
        except Exception as err:
            return None, 'The file dialog failed: {}'.format(err)
        return validate_job_path(path)

    chooser = getattr(vs, 'GetFile', None)
    if chooser is not None:
        try:
            path = dialog_path(chooser())
        except Exception as err:
            return None, 'The file dialog failed: {}'.format(err)
        if not path:
            return None, None
        # This dialog cannot show a .json at all, so a cancel here is more
        # likely "the file I wanted was not listed" than a change of mind.
        found, note = validate_job_path(path)
        if found:
            return found, note
        return None, note

    fallback = job_path()
    if os.path.exists(fallback):
        return fallback, fallback
    return None, ('This Vectorworks offers no file dialog, and there is no\n'
                  '{}\nto fall back on.'.format(fallback))


def validate_job_path(path):
    """Check a chosen path before anything tries to read it."""
    if not path:
        return None, None                      # cancelled; say nothing
    if not os.path.exists(path):
        return None, 'That file no longer exists:\n{}'.format(path)
    if os.path.isdir(path):
        return None, 'That is a folder, not a job file:\n{}'.format(path)
    return path, path


# ═══════════════════════════════════════════════════════════════════════════
# TOOL: FIND AND REPLACE  (writes)
# ═══════════════════════════════════════════════════════════════════════════
#
# Vectorworks' own Find and Replace cannot see inside plug-in object records,
# so none of this is reachable from it. Search finds; this changes.
#
# ONLY the fields that are free text and identify the object are offered:
# device and socket names and tags, and a circuit's Label, Number and Cable.
# Deliberately NOT offered:
#   signal / connector / cable type  chosen from lists; a "correction" would be
#                                    a value ConnectCAD rejects
#   Src_Dev_Name and friends         caches, rewritten on reset
#   loc_room / loc_rack              references to Room and Rack objects
#   make / model / description       library values, not per-instance text
#
# Renaming a device is not a text edit -- it is a rename of a LINK KEY. Every
# equipment item, panel layout and panel connector pointing at the old name has
# to move with it, which is what plan_link_sync does for the other tools and
# does here too. Those follow-on edits are not offered as choices because they
# are not optional: leaving one behind is how a device loses its equipment.

REPLACE_FIELDS = {
    'device': [(DEVICE_NAME_FIELDS, True), (DEVICE_TAG_FIELDS, False)],
    'equipment': [(EQUIP_NAME_FIELDS, True)],
    'socket': [(SOCKET_NAME_FIELDS, True), (SOCKET_TAG_FIELDS, False)],
    'circuit': [(['Label'], False), (['Number'], False), (['Cable'], False)],
}

# What each tick box covers. Equipment rides with devices because an equipment
# item's name IS its device's name -- they are one string in two places.
REPLACE_GROUPS = {
    'devices': ('device', 'equipment'),
    'sockets': ('socket',),
    'circuits': ('circuit',),
}

fFindLbl, fFindEdit = 804, 805
fReplLbl, fReplEdit = 806, 807
fScopeLbl, fScopePopup = 808, 809
fKindLbl, fDevChk, fSktChk, fCircChk = 810, 811, 812, 813
fWholeChk, fCaseChk, fSyncChk, fNoteTxt = 814, 815, 817, 816

gLB, gCountTxt, gAllBtn, gNoneBtn, gHintTxt = 820, 821, 822, 823, 824
GCOL_USE, GCOL_TYPE, GCOL_FIELD, GCOL_OLD, GCOL_NEW = 0, 1, 2, 3, 4
TICK, UNTICK = 'YES', ''


def replace_in_text(value, find, replacement, case_sensitive, whole):
    """The value after replacement, or None if nothing matched.

    Whole-string compares the ENTIRE field, which is how you rename exactly
    'SPK 1.01' without touching 'SPK 1.010'. Otherwise every occurrence inside
    the value is replaced."""
    if not find or value is None:
        return None
    if whole:
        matched = (value == find if case_sensitive
                   else value.lower() == find.lower())
        return replacement if matched and value != replacement else None

    if case_sensitive:
        if find not in value:
            return None
        out = value.replace(find, replacement)
        return out if out != value else None

    # Case-insensitive substring: walk the lowered copy so the untouched parts
    # of the original keep their own casing.
    lowered, needle = value.lower(), find.lower()
    if needle not in lowered:
        return None
    out = []
    index = 0
    while True:
        found = lowered.find(needle, index)
        if found < 0:
            out.append(value[index:])
            break
        out.append(value[index:found])
        out.append(replacement)
        index = found + len(needle)
    result = ''.join(out)
    return result if result != value else None


def find_replacements(handles, find, replacement, kinds, case_sensitive=False,
                      whole=False):
    """Every field that would change. Returns a list of candidate dicts.

    Read-only: this plans, it does not write. What comes back is exactly what
    the table shows, so nothing can change that the user did not see."""
    out = []
    for handle in handles:
        kind = classify(handle)
        if kind is None or kind not in kinds:
            continue
        for candidates, is_link_name in REPLACE_FIELDS.get(kind, []):
            field = resolve_field(handle, candidates)
            if not field:
                continue
            value = read_field(handle, field)
            if is_unnamed(value):
                # '<DEVICE>' and friends are placeholders, not text. Renaming
                # one would turn a sentinel into a name.
                continue
            new = replace_in_text(value, find, replacement, case_sensitive,
                                  whole)
            if new is None or not new.strip():
                continue
            out.append({
                'handle': handle, 'kind': kind, 'field': field,
                'old': value, 'new': new, 'is_link_name': is_link_name,
                'label': object_label(handle, kind),
            })
    return out


def ask_find_replace():
    """Returns the options dict, or None if cancelled."""
    chosen = {}
    dlg = vs.CreateLayout('Find and Replace', False, 'Find', 'Cancel')

    vs.CreateStaticText(dlg, fFindLbl, 'Find:', -1)
    vs.CreateEditText(dlg, fFindEdit, '', 44)
    vs.CreateStaticText(dlg, fReplLbl, 'Replace with:', -1)
    vs.CreateEditText(dlg, fReplEdit, '', 44)

    vs.CreateStaticText(dlg, fScopeLbl, 'Look in:', -1)
    vs.CreatePullDownMenu(dlg, fScopePopup, 26)

    vs.CreateStaticText(dlg, fKindLbl, 'Replace in:', -1)
    vs.CreateCheckBox(dlg, fDevChk, 'Device names and tags')
    vs.CreateCheckBox(dlg, fSktChk, 'Socket names and tags')
    vs.CreateCheckBox(dlg, fCircChk, 'Circuit labels, numbers and cable names')

    vs.CreateCheckBox(dlg, fWholeChk, 'Match the whole string, not part of it')
    vs.CreateCheckBox(dlg, fCaseChk, 'Match case')
    vs.CreateCheckBox(dlg, fSyncChk,
                      'Update linked instances (equipment items, panel '
                      'references)')

    vs.CreateStaticText(
        dlg, fNoteTxt,
        'You will see every proposed change in a list before anything is\n'
        'altered, and can untick any you do not want.\n\n'
        'ConnectCAD links a device to its equipment item by NAME, so leaving\n'
        '"update linked instances" ticked carries panel references and\n'
        'equipment names along with a rename. Unticking it renames only what\n'
        'you picked, which WILL unlink them -- occasionally what you want,\n'
        'usually not.\n\n'
        'Dropdown values, endpoint caches and library fields are never\n'
        'touched.', -1)

    vs.SetFirstLayoutItem(dlg, fFindLbl)
    vs.SetRightItem(dlg, fFindLbl, fFindEdit, 0, 0)
    vs.SetBelowItem(dlg, fFindLbl, fReplLbl, 0, 0)
    vs.SetRightItem(dlg, fReplLbl, fReplEdit, 0, 0)
    vs.SetBelowItem(dlg, fReplLbl, fScopeLbl, 0, 8)
    vs.SetRightItem(dlg, fScopeLbl, fScopePopup, 0, 0)
    vs.SetBelowItem(dlg, fScopeLbl, fKindLbl, 0, 8)
    vs.SetBelowItem(dlg, fKindLbl, fDevChk, 0, 0)
    vs.SetBelowItem(dlg, fDevChk, fSktChk, 0, 0)
    vs.SetBelowItem(dlg, fSktChk, fCircChk, 0, 0)
    vs.SetBelowItem(dlg, fCircChk, fWholeChk, 0, 8)
    vs.SetBelowItem(dlg, fWholeChk, fCaseChk, 0, 0)
    vs.SetBelowItem(dlg, fCaseChk, fSyncChk, 0, 0)
    vs.SetBelowItem(dlg, fSyncChk, fNoteTxt, 0, 10)

    def handler(item, data):
        if item == kSetup:
            # Pull-downs are filled here, with the choice POSITION as the last
            # argument -- building them at construction time gives a menu that
            # opens empty.
            vs.AddChoice(dlg, fScopePopup, 'Selected objects only', 0)
            vs.AddChoice(dlg, fScopePopup, 'Active layer', 1)
            vs.AddChoice(dlg, fScopePopup, 'Whole document', 2)
            vs.SelectChoice(dlg, fScopePopup, SCOPE_DOCUMENT, True)
            vs.SetBooleanItem(dlg, fDevChk, True)
            vs.SetBooleanItem(dlg, fSktChk, True)
            vs.SetBooleanItem(dlg, fCircChk, True)
            vs.SetBooleanItem(dlg, fWholeChk, False)
            vs.SetBooleanItem(dlg, fCaseChk, False)
            # On by default: ConnectCAD ties a device to its equipment item by
            # NAME, so a rename that does not carry the references with it
            # unlinks them.
            vs.SetBooleanItem(dlg, fSyncChk, True)
        elif item == kOK:
            kinds = set()
            if vs.GetBooleanItem(dlg, fDevChk):
                kinds.update(REPLACE_GROUPS['devices'])
            if vs.GetBooleanItem(dlg, fSktChk):
                kinds.update(REPLACE_GROUPS['sockets'])
            if vs.GetBooleanItem(dlg, fCircChk):
                kinds.update(REPLACE_GROUPS['circuits'])
            chosen.update({
                'find': vs.GetItemText(dlg, fFindEdit) or '',
                'replace': vs.GetItemText(dlg, fReplEdit) or '',
                'scope': vs.GetSelectedChoiceIndex(dlg, fScopePopup, 0),
                'kinds': kinds,
                'whole': vs.GetBooleanItem(dlg, fWholeChk),
                'case': vs.GetBooleanItem(dlg, fCaseChk),
                'sync': vs.GetBooleanItem(dlg, fSyncChk),
            })

    if vs.RunLayoutDialog(dlg, handler) != kOK or not chosen:
        return None
    return chosen


def choose_replacements(candidates, find, replacement):
    """Show every proposed change. Returns the ticked ones, or None if cancelled.

    Everything starts ticked: the user asked for these, and having to tick 200
    rows to accept what you just searched for would be absurd. Untick the ones
    you do not want.

    The tick is a text cell rather than a checkbox control. List browsers do
    offer control columns, but their type constants are not documented anywhere
    I could verify, and an unverifiable constant in a dialog that cannot be
    tested from here is how you ship a table nobody can use."""
    state = [True] * len(candidates)
    dlg = vs.CreateLayout('Replace', False, 'Replace', 'Cancel')

    vs.CreateStaticText(
        dlg, gCountTxt,
        '{} change(s) for "{}" -> "{}". Click a row to tick or untick it.'
        .format(len(candidates), find, replacement), -1)
    vs.CreateLB(dlg, gLB, 124, 24)
    vs.CreatePushButton(dlg, gAllBtn, 'Tick all')
    vs.CreatePushButton(dlg, gNoneBtn, 'Untick all')
    vs.CreateStaticText(
        dlg, gHintTxt,
        'Only ticked rows are changed. Equipment items and panel references\n'
        'follow a device rename automatically and are not listed here.', -1)

    vs.SetFirstLayoutItem(dlg, gCountTxt)
    vs.SetBelowItem(dlg, gCountTxt, gLB, 0, 0)
    vs.SetBelowItem(dlg, gLB, gAllBtn, 0, 8)
    vs.SetRightItem(dlg, gAllBtn, gNoneBtn, 4, 0)
    vs.SetBelowItem(dlg, gAllBtn, gHintTxt, 0, 8)

    def paint(row):
        vs.SetLBItemInfo(dlg, gLB, row, GCOL_USE,
                         TICK if state[row] else UNTICK, -1)

    def handler(item, data):
        if item == kSetup:
            # Columns are inserted at increasing indices; repeatedly inserting
            # at 0 is a documented header-rendering bug.
            vs.InsertLBColumn(dlg, gLB, GCOL_USE, 'Replace?', 70)
            vs.InsertLBColumn(dlg, gLB, GCOL_TYPE, 'Type', 90)
            vs.InsertLBColumn(dlg, gLB, GCOL_FIELD, 'Field', 110)
            vs.InsertLBColumn(dlg, gLB, GCOL_OLD, 'Current text', 250)
            vs.InsertLBColumn(dlg, gLB, GCOL_NEW, 'After replacing', 250)
            vs.ShowLBHeader(dlg, gLB, True)
            vs.EnableLBColumnLines(dlg, gLB, True)
            vs.EnableLBSingleLineSelection(dlg, gLB, True)
            # OFF: sorting reorders rows and every stored index goes stale,
            # which would tick the wrong rows. It defaults to ON.
            vs.EnableLBSorting(dlg, gLB, False)

            vs.EnableLBUpdates(dlg, gLB, False)
            for index, row in enumerate(candidates):
                vs.InsertLBItem(dlg, gLB, index, TICK)
                vs.SetLBItemInfo(dlg, gLB, index, GCOL_TYPE, row['kind'], -1)
                vs.SetLBItemInfo(dlg, gLB, index, GCOL_FIELD, row['field'], -1)
                vs.SetLBItemInfo(dlg, gLB, index, GCOL_OLD, row['old'], -1)
                vs.SetLBItemInfo(dlg, gLB, index, GCOL_NEW, row['new'], -1)
            vs.EnableLBUpdates(dlg, gLB, True)
            vs.RefreshLB(dlg, gLB)

        elif item == gLB:
            # The selected row is re-derived by scanning rather than taken from
            # the event: arrow keys and type-ahead move the highlight while
            # reporting rowIndex -1, so trusting the event would toggle
            # whichever row was last clicked.
            row = lb_selected_row(dlg, gLB, len(candidates))
            if 0 <= row < len(candidates):
                state[row] = not state[row]
                paint(row)

        elif item in (gAllBtn, gNoneBtn):
            wanted = (item == gAllBtn)
            vs.EnableLBUpdates(dlg, gLB, False)
            for row in range(len(candidates)):
                state[row] = wanted
                paint(row)
            vs.EnableLBUpdates(dlg, gLB, True)
            vs.RefreshLB(dlg, gLB)

    if vs.RunLayoutDialog(dlg, handler) != kOK:
        return None
    return [c for c, ticked in zip(candidates, state) if ticked]


def tool_find_replace():
    """Returns (status, summary)."""
    asked = ask_find_replace()
    if asked is None:
        return 'cancelled', None
    if not asked['find']:
        vs.AlrtDialog('Nothing to find.')
        return 'stopped', None
    if not asked['kinds']:
        vs.AlrtDialog('No object types were ticked, so there is nothing to '
                      'change.')
        return 'stopped', None

    handles = collect_scope(asked['scope'])
    candidates = find_replacements(handles, asked['find'], asked['replace'],
                                   asked['kinds'], asked['case'],
                                   asked['whole'])
    if not candidates:
        vs.AlrtDialog('No matches for "{}".'.format(asked['find']))
        return 'done', None

    picked = choose_replacements(candidates, asked['find'], asked['replace'])
    if picked is None:
        return 'cancelled', None
    if not picked:
        return 'done', None

    # From here on nothing else is asked. The user has seen every change and
    # said yes to it.
    edits = [make_edit(c['handle'], c['kind'], c['field'], c['old'], c['new'],
                       c['is_link_name']) for c in picked]

    # References to a renamed device follow it, if asked for. Planned AFTER
    # the choice, so unticking a rename drops its follow-on edits with it.
    sync_edits, used_assoc = [], True
    if asked['sync']:
        _walked, parents = walk_document(with_parents=True)
        sync_edits, used_assoc = plan_link_sync(edits, parents)
        sync_edits = dedupe_edits(edits, sync_edits)
    duplicates = find_duplicate_names(edits + sync_edits)

    stranded = unsynced_socket_references(edits, sync_edits) if asked['sync'] \
        else []

    applied = apply_edits(edits + sync_edits)
    reset = reset_circuits()

    lines = report_header('FIND AND REPLACE')
    lines.append('Find:        "{}"'.format(asked['find']))
    lines.append('Replace:     "{}"'.format(asked['replace']))
    lines.append('Match:       {}{}'.format(
        'whole string' if asked['whole'] else 'anywhere in the field',
        ', case-sensitive' if asked['case'] else ''))
    lines.append('Offered:     {}'.format(len(candidates)))
    lines.append('Chosen:      {}'.format(len(picked)))
    if asked['sync']:
        lines.append('Linked refs: {}{}'.format(
            len(sync_edits),
            '' if used_assoc else '  (matched by NAME - no ConnectCAD licence)'))
    else:
        lines.append('Linked refs: NOT UPDATED - you unticked that. Any device '
                     'renamed here')
        lines.append('             is now unlinked from its equipment item.')
    lines.append('Applied:     {}'.format(len(applied)))
    lines.append('Circuits reset: {}'.format(reset))
    lines.append('')
    if duplicates:
        lines.append('NAMES NOW SHARED BY MORE THAN ONE OBJECT')
        lines.append('Not an error on its own -- one device drawn twice is '
                     'normal -- but a')
        lines.append('reference to a duplicated name cannot say which object '
                     'it means.')
        for (kind, name), detail in sorted(duplicates.items())[:20]:
            lines.append('  {:<10} "{}"{}'.format(
                kind, name,
                '  (merged by this run)' if detail['created_here'] else ''))
        lines.append('')
    if stranded:
        lines.append('PANEL CONNECTORS LEFT POINTING AT A RENAMED SOCKET')
        lines.append('These reference a socket name this run changed, but '
                     'their ConnectedDev does')
        lines.append('not match the socket\'s owning device, so nothing '
                     'linked them. Check the')
        lines.append('device name against the connector below, then fix by '
                     'hand or reconcile')
        lines.append('names with Match Names and Display Tags first.')
        for device_name, socket_name in stranded[:20]:
            lines.append('  device "{}"  socket "{}"'.format(
                device_name or '(blank)', socket_name))
        if len(stranded) > 20:
            lines.append('  ... and {} more'.format(len(stranded) - 20))
        lines.append('')

    lines.append('CHANGES')
    lines.extend(format_edits(applied))

    save_text('find_replace', '\n'.join(lines))
    # Nothing is returned for the launcher to report. The user saw every change
    # in the table and approved it; a summary afterwards would be one more
    # dialog to dismiss for news they already have. The full record is in the
    # report either way.
    return 'done', None


# ═══════════════════════════════════════════════════════════════════════════
# TOOL: SEARCH CONNECTCAD OBJECTS  (read-only)
# ═══════════════════════════════════════════════════════════════════════════
#
# Vectorworks' own Find and Replace does not see inside plug-in object records,
# so the values that matter most in a ConnectCAD drawing -- a circuit's cable
# name, a device's model, an endpoint cache -- are unsearchable. This walks
# every field of every ConnectCAD object instead.
#
# Read-only by design. It finds and selects; it never writes. Spell Check is
# where replacement lives, and keeping the two apart means this one can search
# fields that would be dangerous to edit (endpoint caches, dropdown values)
# without ever risking a write to them.

qTermLbl, qTermEdit = 704, 705
qScopeLbl, qScopePopup = 706, 707
qKindLbl, qDevChk, qCircChk, qOtherChk = 708, 709, 710, 711
qCaseChk, qWholeChk, qInternalChk = 712, 713, 714
qNoteTxt = 715

rLB, rCountTxt, rHintTxt = 720, 721, 722
RCOL_OBJECT, RCOL_LABEL, RCOL_FIELD, RCOL_VALUE, RCOL_LAYER = 0, 1, 2, 3, 4

# How many hits the results table shows. A search for a common letter can match
# tens of thousands of fields, and the list browser is not the place to find
# that out. The full set always goes to the CSV, and the cap is reported rather
# than silently applied.
SEARCH_DISPLAY_CAP = 500

# ConnectCAD's own bookkeeping. Searchable on request, hidden by default: a
# drawing has hundreds of __ISNEW / __Version / ControlPoint fields and they
# bury the values anyone is actually looking for.
def is_internal_field(name):
    return name.startswith('__')


def object_label(handle, kind, parents=None):
    """A human identifier for a found object.

    A field name and a value are not enough to act on a hit -- "Cable = HL 1"
    could be any of 372 circuits. This says WHICH object, in the terms the
    drawing uses."""
    if kind == 'device':
        field = resolve_field(handle, DEVICE_NAME_FIELDS)
        name = read_field(handle, field) if field else ''
        return name if not is_unnamed(name) else '(unnamed device)'

    if kind == 'circuit':
        source = read_field(handle, 'Src_Dev_Name')
        src_skt = read_field(handle, 'Src_Skt_Name')
        dest = read_field(handle, 'Dst_Dev_Name')
        dst_skt = read_field(handle, 'Dst_Skt_Name')
        return '{}/{} -> {}/{}'.format(source or '?', src_skt or '?',
                                       dest or '?', dst_skt or '?')

    if kind == 'socket':
        field = resolve_field(handle, SOCKET_NAME_FIELDS)
        name = read_field(handle, field) if field else ''
        owner = owning_device(handle, parents or {})
        if owner is not None:
            owner_field = resolve_field(owner, DEVICE_NAME_FIELDS)
            owner_name = read_field(owner, owner_field) if owner_field else ''
            if not is_unnamed(owner_name):
                return '{} / {}'.format(owner_name, name or '?')
        return name or '(unnamed socket)'

    if kind == 'equipment':
        field = resolve_field(handle, EQUIP_NAME_FIELDS)
        return read_field(handle, field) if field else ''

    return get_pio_name(handle)


def field_matches(value, term, case_sensitive, whole_value):
    """Does one field value match?

    `whole_value` compares the entire field rather than looking for the term
    inside it -- which is how you find a field that is EXACTLY '???' or exactly
    blank, neither of which a substring search can express."""
    if not case_sensitive:
        value = value.lower()
        term = term.lower()
    return value == term if whole_value else term in value


def search_objects(term, handles, kinds, parents=None, case_sensitive=False,
                   whole_value=False, include_internal=False):
    """Every field of every matching object that contains `term`.

    Returns a list of hit dicts. One object can produce several hits: a device
    whose name AND model both contain the term is two findings, because they
    are two different things to look at."""
    hits = []
    for handle in handles:
        kind = classify(handle)
        if kind is None or kind not in kinds:
            continue
        label = object_label(handle, kind, parents)
        layer = layer_name(handle)
        record = get_pio_name(handle)
        for field, value in get_fields(handle):
            if not include_internal and is_internal_field(field):
                continue
            if not field_matches(value or '', term, case_sensitive, whole_value):
                continue
            hits.append({
                'handle': handle,
                'kind': kind,
                'record': record,
                'label': label,
                'field': field,
                'value': value or '',
                'layer': layer,
            })
    return hits


def ask_search():
    """Returns (term, scope, kinds, case_sensitive, whole, internal) or None."""
    chosen = {}
    dlg = vs.CreateLayout('Search ConnectCAD Objects', False, 'Search', 'Cancel')

    vs.CreateStaticText(dlg, qTermLbl, 'Find:', -1)
    vs.CreateEditText(dlg, qTermEdit, '', 44)

    vs.CreateStaticText(dlg, qScopeLbl, 'Look in:', -1)
    # The choices go in during kSetup, not here -- see the handler.
    vs.CreatePullDownMenu(dlg, qScopePopup, 26)

    vs.CreateStaticText(dlg, qKindLbl, 'Objects:', -1)
    vs.CreateCheckBox(dlg, qDevChk, 'Devices')
    vs.CreateCheckBox(dlg, qCircChk, 'Circuits')
    vs.CreateCheckBox(dlg, qOtherChk, 'Sockets, equipment and panels')

    vs.CreateCheckBox(dlg, qCaseChk, 'Match case')
    vs.CreateCheckBox(dlg, qWholeChk, 'Match the whole field, not part of it')
    vs.CreateCheckBox(dlg, qInternalChk,
                      'Include ConnectCAD internal fields (__ISNEW, control '
                      'points\u2026)')

    vs.CreateStaticText(
        dlg, qNoteTxt,
        'Searches EVERY field, including ones Vectorworks\' own Find and\n'
        'Replace cannot see: cable names, signals, endpoint caches, makes\n'
        'and models. Read-only \u2014 it finds and selects, it never edits.\n\n'
        'Leave Find empty and tick "whole field" to list blank fields.', -1)

    vs.SetFirstLayoutItem(dlg, qTermLbl)
    vs.SetRightItem(dlg, qTermLbl, qTermEdit, 0, 0)
    vs.SetBelowItem(dlg, qTermLbl, qScopeLbl, 0, 8)
    vs.SetRightItem(dlg, qScopeLbl, qScopePopup, 0, 0)
    vs.SetBelowItem(dlg, qScopeLbl, qKindLbl, 0, 8)
    vs.SetBelowItem(dlg, qKindLbl, qDevChk, 0, 0)
    vs.SetBelowItem(dlg, qDevChk, qCircChk, 0, 0)
    vs.SetBelowItem(dlg, qCircChk, qOtherChk, 0, 0)
    vs.SetBelowItem(dlg, qOtherChk, qCaseChk, 0, 8)
    vs.SetBelowItem(dlg, qCaseChk, qWholeChk, 0, 0)
    vs.SetBelowItem(dlg, qWholeChk, qInternalChk, 0, 0)
    vs.SetBelowItem(dlg, qInternalChk, qNoteTxt, 0, 10)

    def handler(item, data):
        if item == kSetup:
            # A pull-down has to be filled in kSetup, and AddChoice's last
            # argument is the POSITION of the choice, not a flag. Building the
            # menu at construction time and passing -1 gives a pull-down that
            # opens empty and never reports a selection -- which is exactly
            # what this did.
            vs.AddChoice(dlg, qScopePopup, 'Selected objects only', 0)
            vs.AddChoice(dlg, qScopePopup, 'Active layer', 1)
            vs.AddChoice(dlg, qScopePopup, 'Whole document', 2)
            vs.SelectChoice(dlg, qScopePopup, SCOPE_DOCUMENT, True)
            # Devices and circuits carry what people search for; the rest is
            # opt-in so a search does not drown in socket rows.
            vs.SetBooleanItem(dlg, qDevChk, True)
            vs.SetBooleanItem(dlg, qCircChk, True)
            vs.SetBooleanItem(dlg, qOtherChk, False)
            vs.SetBooleanItem(dlg, qCaseChk, False)
            vs.SetBooleanItem(dlg, qWholeChk, False)
            vs.SetBooleanItem(dlg, qInternalChk, False)
        elif item == kOK:
            kinds = set()
            if vs.GetBooleanItem(dlg, qDevChk):
                kinds.add('device')
            if vs.GetBooleanItem(dlg, qCircChk):
                kinds.add('circuit')
            if vs.GetBooleanItem(dlg, qOtherChk):
                kinds.update(('socket', 'equipment', 'panel', 'panelconnector'))
            chosen.update({
                'term': vs.GetItemText(dlg, qTermEdit) or '',
                'scope': vs.GetSelectedChoiceIndex(dlg, qScopePopup, 0),
                'kinds': kinds,
                'case': vs.GetBooleanItem(dlg, qCaseChk),
                'whole': vs.GetBooleanItem(dlg, qWholeChk),
                'internal': vs.GetBooleanItem(dlg, qInternalChk),
            })

    if vs.RunLayoutDialog(dlg, handler) != kOK or not chosen:
        return None
    return chosen


def show_search_results(hits, term, capped, path):
    """List the hits. Returns True if the user asked to select them.

    This table IS the result. Everything the run has to say -- the count, the
    cap, where the CSV went -- belongs here, where it can be read next to the
    matches, rather than in an alert that has to be dismissed after the table
    has already been closed."""
    shown = hits[:SEARCH_DISPLAY_CAP]
    dlg = vs.CreateLayout('Search Results', False, 'Select in drawing', 'Close')

    heading = '{} match(es) for "{}"'.format(len(hits), term)
    if capped:
        heading += '  -- showing the first {}; the report has them all'.format(
            SEARCH_DISPLAY_CAP)
    vs.CreateStaticText(dlg, rCountTxt, heading, -1)
    vs.CreateLB(dlg, rLB, 118, 24)
    vs.CreateStaticText(
        dlg, rHintTxt,
        '"Select in drawing" selects every matching object, so Fit to '
        'Selection\nwill take you to them.\n\nAll {} match(es) written to:\n{}'
        .format(len(hits), path), -1)

    vs.SetFirstLayoutItem(dlg, rCountTxt)
    vs.SetBelowItem(dlg, rCountTxt, rLB, 0, 0)
    vs.SetBelowItem(dlg, rLB, rHintTxt, 0, 8)

    def handler(item, data):
        if item == kSetup:
            vs.InsertLBColumn(dlg, rLB, RCOL_OBJECT, 'Object', 90)
            vs.InsertLBColumn(dlg, rLB, RCOL_LABEL, 'Which one', 260)
            vs.InsertLBColumn(dlg, rLB, RCOL_FIELD, 'Field', 150)
            vs.InsertLBColumn(dlg, rLB, RCOL_VALUE, 'Value', 260)
            vs.InsertLBColumn(dlg, rLB, RCOL_LAYER, 'Layer', 110)
            vs.ShowLBHeader(dlg, rLB, True)
            vs.EnableLBColumnLines(dlg, rLB, True)
            vs.EnableLBSingleLineSelection(dlg, rLB, True)
            # Off for the same reason as the vocabulary table: sorting
            # invalidates every stored row index.
            vs.EnableLBSorting(dlg, rLB, False)

            vs.EnableLBUpdates(dlg, rLB, False)
            for index, hit in enumerate(shown):
                vs.InsertLBItem(dlg, rLB, index, hit['record'])
                vs.SetLBItemInfo(dlg, rLB, index, RCOL_LABEL, hit['label'], -1)
                vs.SetLBItemInfo(dlg, rLB, index, RCOL_FIELD, hit['field'], -1)
                vs.SetLBItemInfo(dlg, rLB, index, RCOL_VALUE, hit['value'], -1)
                vs.SetLBItemInfo(dlg, rLB, index, RCOL_LAYER, hit['layer'], -1)
            vs.EnableLBUpdates(dlg, rLB, True)
            vs.RefreshLB(dlg, rLB)

    return vs.RunLayoutDialog(dlg, handler) == kOK


def select_hits(hits):
    """Select every matched object. Returns how many were selected."""
    try:
        vs.DSelectAll()
    except Exception:
        pass
    seen = set()
    for hit in hits:
        handle = hit['handle']
        if handle in seen:
            continue
        seen.add(handle)
        try:
            vs.SetSelect(handle)
        except Exception:
            pass
    return len(seen)


def tool_search():
    """Returns (status, summary)."""
    asked = ask_search()
    if asked is None:
        return 'cancelled', None
    if not asked['kinds']:
        vs.AlrtDialog('No object types were ticked, so there is nothing to '
                      'search.')
        return 'stopped', None

    term = asked['term']
    if not term and not asked['whole']:
        vs.AlrtDialog('Nothing to find.\n\nType something, or tick "Match the '
                      'whole field" to list fields that are empty.')
        return 'stopped', None

    handles = collect_scope(asked['scope'])
    _walked, parents = walk_document(with_parents=True)
    hits = search_objects(term, handles, asked['kinds'], parents,
                          asked['case'], asked['whole'], asked['internal'])

    if not hits:
        vs.AlrtDialog('No matches for "{}".'.format(term))
        return 'done', None

    rows = [['Object', 'Which one', 'Field', 'Value', 'Layer']]
    for hit in hits:
        rows.append([hit['record'], hit['label'], hit['field'], hit['value'],
                     hit['layer']])
    path = save_csv('search', rows)

    if show_search_results(hits, term, len(hits) > SEARCH_DISPLAY_CAP, path):
        select_hits(hits)
    # Nothing is returned for the launcher to report. Search is read-only and
    # has already shown its results; a summary here would be a second dialog
    # restating what the table just said, and a third if the run also selected.
    return 'done', None


# ─── Preferences dialog ──────────────────────────────────────────────────────
#
# Item numbers are in the 600s; every other dialog in this file has its own
# hundred (100s normalise, 200s match, 300s launcher, 400s spell, 500s vocab).

pColLbl, pColEdit = 604, 605
pRowLbl, pRowEdit = 606, 607
pGapLbl, pGapEdit = 608, 609
pStackLbl, pStackEdit = 615, 616
pElbowLbl, pElbowEdit = 617, 618
pTypeLbl, pTypePopup = 610, 611
pLabelLbl, pLabelEdit = 612, 613
pNote = 614


def read_number(dialog, item, current, key):
    """One edit field back as a number, clamped, falling back to `current`.

    A field left blank or filled with nonsense keeps the value that was in it
    rather than resetting to a default -- silently changing a spacing the user
    did not touch would be worse than ignoring what they typed."""
    try:
        value = float((vs.GetItemText(dialog, item) or '').strip())
    except (TypeError, ValueError):
        return current
    low, high = PREF_RANGES.get(key, (None, None))
    if low is not None and not (low <= value <= high):
        return current
    return value


def tool_preferences():
    """Returns (status, summary)."""
    prefs = load_prefs()
    chosen = {}

    dialog = vs.CreateLayout('CC Tools Preferences', False, 'Save', 'Cancel')

    vs.CreateStaticText(dialog, pColLbl, 'Column spacing (inches):', -1)
    vs.CreateEditText(dialog, pColEdit, '{:g}'.format(prefs['column_inches']), 10)
    vs.CreateStaticText(dialog, pRowLbl, 'Row spacing (inches):', -1)
    vs.CreateEditText(dialog, pRowEdit, '{:g}'.format(prefs['row_inches']), 10)
    vs.CreateStaticText(dialog, pGapLbl, 'Gap between sections (inches):', -1)
    vs.CreateEditText(dialog, pGapEdit,
                      '{:g}'.format(prefs['section_gap_inches']), 10)
    vs.CreateStaticText(dialog, pStackLbl, 'Gap between stacked devices:', -1)
    vs.CreateEditText(dialog, pStackEdit,
                      '{:g}'.format(prefs['device_gap_inches']), 10)
    vs.CreateStaticText(dialog, pElbowLbl, 'Circuit elbow stagger (0 = off):', -1)
    vs.CreateEditText(dialog, pElbowEdit,
                      '{:g}'.format(prefs['circuit_stagger_inches']), 10)

    vs.CreateStaticText(dialog, pTypeLbl, 'Circuit line mode:', -1)
    # Filled in kSetup, for the same reason as the search dialog's.
    vs.CreatePullDownMenu(dialog, pTypePopup, 18)

    vs.CreateStaticText(dialog, pLabelLbl, 'Device label symbol:', -1)
    vs.CreateEditText(dialog, pLabelEdit, prefs['label_symbol'], 22)

    vs.CreateStaticText(
        dialog, pNote,
        'Spacing is in printed inches and is scaled by the layer, so a job\n'
        'drawn on a 1:2 layer keeps the same proportions.\n\n'
        'Sections are laid out as bands down the drawing, in the order the\n'
        'job lists them. Leave the label symbol blank to keep ConnectCAD\'s.', -1)

    vs.SetFirstLayoutItem(dialog, pColLbl)
    vs.SetRightItem(dialog, pColLbl, pColEdit, 0, 0)
    vs.SetBelowItem(dialog, pColLbl, pRowLbl, 0, 0)
    vs.SetRightItem(dialog, pRowLbl, pRowEdit, 0, 0)
    vs.SetBelowItem(dialog, pRowLbl, pGapLbl, 0, 0)
    vs.SetRightItem(dialog, pGapLbl, pGapEdit, 0, 0)
    vs.SetBelowItem(dialog, pGapLbl, pStackLbl, 0, 0)
    vs.SetRightItem(dialog, pStackLbl, pStackEdit, 0, 0)
    vs.SetBelowItem(dialog, pStackLbl, pElbowLbl, 0, 0)
    vs.SetRightItem(dialog, pElbowLbl, pElbowEdit, 0, 0)
    vs.SetBelowItem(dialog, pElbowLbl, pTypeLbl, 0, 8)
    vs.SetRightItem(dialog, pTypeLbl, pTypePopup, 0, 0)
    vs.SetBelowItem(dialog, pTypeLbl, pLabelLbl, 0, 0)
    vs.SetRightItem(dialog, pLabelLbl, pLabelEdit, 0, 0)
    vs.SetBelowItem(dialog, pLabelLbl, pNote, 0, 10)

    def handler(item, data):
        if item == kSetup:
            for position, name in enumerate(CIRCUIT_TYPES):
                vs.AddChoice(dialog, pTypePopup,
                             name or '(leave as ConnectCAD sets it)', position)
            current = prefs.get('circuit_type', '')
            index = CIRCUIT_TYPES.index(current) if current in CIRCUIT_TYPES else 0
            vs.SelectChoice(dialog, pTypePopup, index, True)
        elif item == kOK:
            picked = vs.GetSelectedChoiceIndex(dialog, pTypePopup, 0)
            chosen.update({
                'column_inches': read_number(dialog, pColEdit,
                                             prefs['column_inches'],
                                             'column_inches'),
                'row_inches': read_number(dialog, pRowEdit, prefs['row_inches'],
                                          'row_inches'),
                'section_gap_inches': read_number(dialog, pGapEdit,
                                                  prefs['section_gap_inches'],
                                                  'section_gap_inches'),
                'device_gap_inches': read_number(dialog, pStackEdit,
                                                 prefs['device_gap_inches'],
                                                 'device_gap_inches'),
                'circuit_stagger_inches': read_number(
                    dialog, pElbowEdit, prefs['circuit_stagger_inches'],
                    'circuit_stagger_inches'),
                'circuit_type': (CIRCUIT_TYPES[picked]
                                 if 0 <= picked < len(CIRCUIT_TYPES) else ''),
                'label_symbol': (vs.GetItemText(dialog, pLabelEdit) or '').strip(),
            })

    if vs.RunLayoutDialog(dialog, handler) != kOK or not chosen:
        return 'cancelled', None

    path = save_prefs(chosen)
    if path is None:
        vs.AlrtDialog('Could not write preferences to:\n{}'.format(prefs_path()))
        return 'stopped', 'preferences could not be saved'

    summary = ('columns {:g}"  rows {:g}"  section gap {:g}"'.format(
        chosen['column_inches'], chosen['row_inches'],
        chosen['section_gap_inches']))
    if chosen['circuit_type']:
        summary += '  line mode {}'.format(chosen['circuit_type'])
    vs.AlrtDialog('Preferences saved to:\n{}\n\n{}'.format(path, summary))
    return 'done', summary


# ─── Export a prompt ─────────────────────────────────────────────────────────
def build_prompt(profile, reference, catalogue):
    """Everything a model needs to design a schematic for THIS drawing.

    The conventions come from the drawing itself rather than from a description
    of it, and a real worked example is included because an example in the
    exact output format teaches more than any amount of prose about it."""
    import json

    lines = []
    lines.append('You are designing a ConnectCAD signal-flow schematic for '
                 'Vectorworks.')
    lines.append('')
    lines.append('Reply with ONE JSON object and nothing else -- no commentary, '
                 'no code fence.')
    lines.append('')
    lines.append('=' * 74)
    lines.append('THE JOB FORMAT')
    lines.append('=' * 74)
    lines.append(JOB_FORMAT)
    lines.append('')
    lines.append('Rules that matter:')
    lines.append('- Device names are the link key. They must be unique unless '
                 'you deliberately')
    lines.append('  mean the same physical device drawn twice.')
    lines.append('- Every circuit endpoint must name a device in "devices" and '
                 'a socket on it.')
    lines.append('- Signal flows left to right: put sources in lower columns '
                 'than destinations.')
    lines.append('- Prefer makes and models this drawing already uses; a device '
                 'with a matching')
    lines.append('  symbol is built from it exactly, sockets and all.')
    lines.append('')

    lines.append('=' * 74)
    lines.append('HOW THIS DRAWING IS BUILT')
    lines.append('=' * 74)
    lines.extend(profile_report_lines(profile))

    if catalogue:
        lines.append('Device symbols available (these build exactly, no '
                     'sockets needed):')
        for entry in catalogue:
            if entry['make'] or entry['model']:
                lines.append('  {} {}   ({} socket(s))'.format(
                    entry['make'], entry['model'], entry['sockets']))
        lines.append('')

    if reference and reference.get('devices'):
        lines.append('=' * 74)
        lines.append('A WORKED EXAMPLE FROM THIS DRAWING')
        lines.append('=' * 74)
        lines.append('Real devices and wiring, in the same shape your reply '
                     'should take:')
        lines.append('')
        sample = {
            'devices': reference['devices'][:8],
            'circuits': reference['circuits'][:12],
        }
        lines.append(json.dumps(sample, indent=2))
        lines.append('')

    lines.append('=' * 74)
    lines.append('WHAT TO DESIGN')
    lines.append('=' * 74)
    lines.append('Describe what you want below this line, then send the whole '
                 'message.')
    lines.append('')
    lines.append('>>> ')
    return '\n'.join(lines)


def tool_export_prompt():
    """Returns (status, summary)."""
    handles = collect_scope(SCOPE_DOCUMENT)
    _walked, parents = walk_document(with_parents=True)
    profile = build_document_profile(handles, parents)
    reference = build_reference(handles)
    catalogue = device_symbol_catalogue()

    text = build_prompt(profile, reference, catalogue)
    os.makedirs(BASE_FOLDER, exist_ok=True)
    path = os.path.join(BASE_FOLDER, PROMPT_FILE)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)

    vs.AlrtDialog(
        'Document profile written to:\n{}\n\n'
        'This describes how THIS drawing is built, so new work matches it.\n\n'
        '1. Start a Claude conversation and attach JOB-SPEC.md.\n'
        '2. Attach this file too, so it follows your conventions.\n'
        '3. Describe what you want. Claude replies with a .json file.\n'
        '4. Download it, then run CC Tools > Draw schematic job and\n'
        '   pick the file.'.format(path))
    return 'done', 'prompt for {} device(s) written to\n{}'.format(
        len(profile['device_models']), path)


# ─── The golden device list ──────────────────────────────────────────────────
#
# A curated markdown file of devices and their real connectors, kept in
# ~/Documents/CC Tools/, seeded from the device list at the end of
# JOB-SPEC.md -- the same one file the user hands Claude.
#
# WHY THIS EXISTS, given ConnectCAD already ships a database of 2,734 devices:
# consistency. The shipped data is uneven -- socket naming varies by
# manufacturer, and 36 rows carry a double space in a name. A curated file is a
# place to pin down how YOUR house draws a device, once, so every schematic
# that uses it comes out the same.
#
# It is markdown, not JSON, for one reason that matters: the same file is
# handed to Claude alongside JOB-SPEC.md. Claude reads the socket names from
# it and writes circuits against them; the plug-in reads the same names and
# builds the sockets. Both sides work from one source, so they cannot disagree.
# A device NOT in this file is where a model would otherwise guess -- and that
# is exactly when it should be looked up and added here instead.
#
# FORMAT -- a heading naming the device, then a table:
#
#     ## Meyer Sound | TIGRA-L
#
#     | Socket | Type | Signal | Connector | Side |
#     |---|---|---|---|---|
#     | LAN_IN 1 | IN | LAN | EC-6A | L |
#
# Columns are found by their HEADER NAME, not their position, so the order can
# change and extra columns are ignored. Prose between entries is ignored too,
# which is what makes it a document rather than a data file.

# The user copies ONE file here -- the spec they hand Claude, which carries the
# device list at the end. Either name is accepted so nobody has to rename it.
GOLDEN_FILE = 'devices.md'
GOLDEN_FILES = ('devices.md', 'JOB-SPEC.md', 'job-spec.md')
GOLDEN_COLUMNS = ('socket', 'type', 'signal', 'connector', 'side')

# Physical properties, written as "- Key: value" lines between a device's
# heading and its socket table. They map onto ConnectCAD's EquipItem record,
# which is where they end up when a device is placed in a rack:
#
#   Width / Height / Depth  ->  Width, Height, Depth
#   Weight                  ->  weight
#   Power                   ->  power
#   Rack mounted            ->  width_R  ('full-rack', 'half-rack', or not racked)
#   Rack U                  ->  heightU
#
# Rack U is the device's SIZE in rack units, not its position in a rack. The
# EquipItem field called 'rack U' -- with a space -- is the position, and that
# belongs to an installation rather than to the product.
GOLDEN_PROPERTIES = ('width', 'height', 'depth', 'weight', 'power',
                     'rack mounted', 'rack u')

_golden_cache = {}


def golden_path():
    """The curated list, whichever accepted name it was saved under."""
    for name in GOLDEN_FILES:
        candidate = os.path.join(BASE_FOLDER, name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(BASE_FOLDER, GOLDEN_FILE)


def split_table_row(line):
    """Cells of one markdown table row, outer pipes discarded."""
    line = line.strip()
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|'):
        line = line[:-1]
    return [c.strip() for c in line.split('|')]


def is_table_divider(line):
    """The |---|---| line under a markdown header row."""
    cells = split_table_row(line)
    if not cells:
        return False
    return all(c and set(c) <= set('-: ') for c in cells)


def parse_golden_devices(text):
    """{(make, model): [socket dicts]} from the curated markdown.

    Anything that is not a device heading followed by a table is ignored, so
    the file can carry as much explanation as it needs to stay maintainable."""
    devices = {}
    current = None
    header = None
    fenced = False
    for raw in text.split('\n'):
        line = raw.strip()

        # Skip fenced code blocks. The format is documented BY EXAMPLE inside
        # this same file, so without this the example device is parsed as a
        # real one -- and the file now carries the whole job spec, which has
        # examples of its own.
        if line.startswith('```') or line.startswith('~~~'):
            fenced = not fenced
            continue
        if fenced:
            continue

        if line.startswith('##') and '|' in line:
            title = line.lstrip('#').strip()
            make, _sep, model = title.partition('|')
            make, model = make.strip(), model.strip()
            current = {'make': make, 'model': model, 'sockets': [],
                       'properties': {}}
            devices[(normalise_model(make), normalise_model(model))] = current
            header = None
            continue

        # "- Key: value" between the heading and the table.
        if line.startswith('-') and ':' in line and current is not None:
            key, _sep, value = line.lstrip('-').strip().partition(':')
            key = key.strip().lower()
            value = value.strip()
            if key in GOLDEN_PROPERTIES and value and value not in ('-', '--'):
                current['properties'][key] = value
            continue

        if not line.startswith('|'):
            if not line:
                header = None
            continue
        if current is None:
            continue

        cells = split_table_row(line)
        if header is None:
            lowered = [c.lower() for c in cells]
            if 'socket' in lowered:
                header = lowered
            continue
        if is_table_divider(line):
            continue

        row = {}
        for name in GOLDEN_COLUMNS:
            row[name] = (cells[header.index(name)].strip()
                         if name in header and header.index(name) < len(cells)
                         else '')
        if row['socket']:
            current['sockets'].append(row)
    return devices


def load_golden_devices():
    """The curated list, or {} if the user has not installed one."""
    if _golden_cache:
        return _golden_cache
    try:
        with open(golden_path(), 'r', encoding='utf-8') as f:
            _golden_cache.update(parse_golden_devices(f.read()))
    except Exception:
        pass
    return _golden_cache


def golden_socket_specs(entry):
    """A curated device's sockets as builder specs."""
    specs = []
    for row in entry['sockets']:
        name = (row.get('socket') or '').strip()
        if not name:
            continue
        side = -1 if (row.get('side') or '').strip().upper().startswith('L') else 1
        specs.append(('skt_L' if side < 0 else 'skt_R', name,
                      (row.get('type') or 'IO').upper(), side,
                      (row.get('signal') or '').strip(),
                      (row.get('connector') or '').strip()))
    return specs


def golden_property(entry, key, default=''):
    """One physical property of a curated device, or a default.

    Values are kept as written -- "482.6 mm", "19 in", "1U" -- rather than
    converted, because the file is read by people as well as by this code and
    an unlabelled number is a unit waiting to be guessed wrong."""
    if not entry:
        return default
    return (entry.get('properties') or {}).get(key.lower(), default)


def golden_number(entry, key):
    """A property as a float, ignoring any unit suffix. None if absent.

    Returns the number only; the caller has to know what unit it wanted, which
    is why golden_property exists alongside this."""
    import re
    raw = golden_property(entry, key)
    if not raw:
        return None
    match = re.search(r'-?\d+(?:\.\d+)?', raw.replace(',', ''))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def golden_is_rack_mounted(entry):
    """True, False, or None when the curated list does not say."""
    raw = golden_property(entry, 'rack mounted').strip().lower()
    if not raw:
        return None
    if raw in ('yes', 'y', 'true', 'full-rack', 'half-rack', 'rack'):
        return True
    if raw in ('no', 'n', 'false', 'none', 'not racked'):
        return False
    return None


def find_golden_device(make, model):
    """The curated entry for a make/model, or None."""
    if not model:
        return None
    return load_golden_devices().get((normalise_model(make),
                                      normalise_model(model)))


# ─── ConnectCAD's shipped device database ────────────────────────────────────
#
# 2,734 real devices with their real socket sets. Looking a make/model up here
# beats letting a language model invent connectors: a Shure ULXD4Q has the
# sockets Shure gave it, and no amount of plausible guessing will match them.
#
# FORMAT, verified against the file rather than assumed:
#   Tab-separated, 24 columns, NO header row -- line 0 is already a device.
#   Line terminator is CRLF. Read it as BYTES and normalise the endings by
#   hand: opening in text mode lets Python's universal newlines mangle it.
#   Encoding is UTF-8 with a BOM, hence utf-8-sig.
#
#   A device owns a BLOCK: it starts on any row where make or model is
#   non-empty and runs to the next such row. Its first row carries both the
#   device AND its first socket.
#
#   Each row is a socket SERIES, not one socket: column 15 is a quantity, and
#   the name is the prefix with the number appended VERBATIM -- no separator
#   is inserted. That is not a guess. 311 quantity>1 rows carry a deliberate
#   trailing space in the prefix ('MIC ' -> 'MIC 1') while 4,680 deliberately
#   do not ('HDV_OUT' -> 'HDV_OUT1'); inserting a space would turn the first
#   group into 'MIC  1'. The binary's own format literal is '%s%d'.

DEVICE_DB_RELATIVE = os.path.join(
    'Libraries', 'Defaults', 'ConnectCAD', 'ConnectCAD_Database',
    'ConnectCAD Devices DB.txt')

DB_MAKE, DB_MODEL = 0, 1
DB_CONN, DB_QTY, DB_SIDE, DB_NAME, DB_SIGNAL, DB_TYPE = 14, 15, 16, 17, 18, 19
DB_COLUMNS = 20          # the lowest column count a usable row can have

# Parsing 17,127 lines is not free and a job may ask about many devices, so the
# parsed form is kept for the life of the command.
_device_db_cache = {}


def device_db_paths():
    """Where the database might be, application copy first.

    ConnectCAD merges an application copy with a per-user one. The user copy is
    read second so its rows win, which is the same precedence ConnectCAD uses.
    """
    found = []
    for base in ('/Applications/Vectorworks 2026',
                 os.path.expanduser('~/Library/Application Support/'
                                    'Vectorworks/2026')):
        path = os.path.join(base, DEVICE_DB_RELATIVE)
        if os.path.exists(path):
            found.append(path)
    return found


def parse_device_db(text):
    """Rows -> {(make, model): [socket row, ...]}, keyed forgivingly.

    Blocks are delimited by a non-empty make or model, and a device's own row
    also carries its first socket."""
    devices = {}
    current = None
    for line in text.split('\n'):
        if not line:
            continue
        row = line.split('\t')
        if len(row) < DB_COLUMNS:
            continue
        make = row[DB_MAKE].strip()
        model = row[DB_MODEL].strip()
        if make or model:
            current = {'make': make, 'model': model, 'rows': []}
            devices[(normalise_model(make), normalise_model(model))] = current
        if current is None:
            continue
        if row[DB_NAME].strip() or row[DB_CONN].strip():
            current['rows'].append(row)
    return devices


def load_device_db():
    """The parsed database, or {} if it is not installed."""
    if _device_db_cache:
        return _device_db_cache
    for path in device_db_paths():
        try:
            with open(path, 'rb') as f:
                raw = f.read().decode('utf-8-sig')
        except Exception:
            continue
        # The application and user copies do not agree on line endings, so
        # both are normalised rather than trusting either.
        raw = raw.replace('\r\n', '\n').replace('\r', '\n')
        _device_db_cache.update(parse_device_db(raw))
    return _device_db_cache


def db_socket_specs(entry):
    """One database device's sockets, expanded, as builder specs.

    A quantity of 4 becomes four sockets. The final name is stripped: 170 rows
    carry a trailing space that would otherwise produce a socket name ending in
    one -- and a trailing space is invisible on screen while making the name a
    different string to everything that references it."""
    specs = []
    for row in entry['rows']:
        prefix = row[DB_NAME]
        connector = row[DB_CONN].strip()
        signal = row[DB_SIGNAL].strip()
        socket_type = (row[DB_TYPE].strip() or 'IO').upper()
        side = -1 if row[DB_SIDE].strip().upper().startswith('L') else 1
        symbol = 'skt_L' if side < 0 else 'skt_R'
        try:
            quantity = int(row[DB_QTY].strip() or '1')
        except ValueError:
            quantity = 1
        quantity = max(1, min(quantity, 128))

        for index in range(quantity):
            name = (prefix if quantity == 1
                    else '{}{}'.format(prefix, index + 1)).strip()
            if not name:
                continue
            specs.append((symbol, name, socket_type, side, signal, connector))
    return specs


def find_db_device(make, model):
    """The database entry for a make/model, or None.

    Matching is the same forgiving comparison used for device symbols, since
    the same product is written 'Galaxy 408', 'GALAXY-408' and 'Galaxy_408'
    depending on who typed it."""
    if not model:
        return None
    database = load_device_db()
    if not database:
        return None
    return database.get((normalise_model(make), normalise_model(model)))


# ─── Read a job ──────────────────────────────────────────────────────────────
def read_job(path=None):
    """Load and validate a job file. Returns (job, problems).

    Validation is deliberately strict and reported all at once: a job is
    written by a language model, and a circuit naming a device that does not
    exist should be a message, not a half-built schematic."""
    import json
    if path is None:
        path = job_path()
    label = os.path.basename(path) or JOB_FILE
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return None, ['No job file found at {}.'.format(path)]
    except Exception as err:
        return None, ['Could not read {}: {}'.format(label, err)]

    # A pasted reply often arrives wrapped in a code fence.
    stripped = text.strip()
    if stripped.startswith('```'):
        stripped = stripped.split('\n', 1)[-1]
        if stripped.rstrip().endswith('```'):
            stripped = stripped.rstrip()[:-3]

    try:
        job = json.loads(stripped)
    except Exception as err:
        return None, ['{} is not valid JSON: {}'.format(label, err)]

    problems = []
    devices = job.get('devices')
    if not isinstance(devices, list) or not devices:
        problems.append('No "devices" list in the job.')
        return None, problems

    # Keyed by ID, not name. A physical device is drawn again in each section
    # it appears in, so names repeat by design; ids are what must be unique.
    ids = {}
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            problems.append('Device {} is not an object.'.format(index))
            continue
        name = (device.get('name') or '').strip()
        if not name:
            problems.append('Device {} has no name.'.format(index))
            continue
        ident = job_device_id(device)
        if ident in ids:
            problems.append('Two devices share the id "{}". Give the repeats '
                            'their own "id" -- the same device drawn in two '
                            'sections needs one id each, so circuits can say '
                            'which they mean.'.format(ident))
        ids[ident] = device

    for index, circuit in enumerate(job.get('circuits') or []):
        if not isinstance(circuit, dict):
            problems.append('Circuit {} is not an object.'.format(index))
            continue
        ends = []
        for end in ('from', 'to'):
            side = circuit.get(end)
            if not isinstance(side, dict) or not side.get('device'):
                problems.append('Circuit {} has no "{}" device.'.format(index, end))
                continue
            if side['device'] not in ids:
                problems.append('Circuit {} connects to "{}", which is not a '
                                'device id in this job.'.format(
                                    index, side['device']))
                continue
            ends.append(ids[side['device']])

        # A circuit is wired by horizontal alignment, and sections are separate
        # bands of the drawing. One that spans two of them cannot ever wire.
        if len(ends) == 2:
            first = (ends[0].get('section') or '').strip()
            second = (ends[1].get('section') or '').strip()
            if first != second:
                problems.append(
                    'Circuit {} runs from section "{}" to section "{}". '
                    'Sections are separate regions of the drawing, so a '
                    'circuit across them cannot be wired -- draw the device '
                    'again in the other section instead.'.format(
                        index, first or '(none)', second or '(none)'))
    return job, problems


# ─── Draw a job ──────────────────────────────────────────────────────────────
def job_device_id(device):
    """How a job refers to this device.

    A physical device is drawn again in each section it appears in -- a speaker
    shows up in the speaker section AND in the power section -- so device NAMES
    legitimately repeat within one job. The id is what circuits point at, and
    it is what has to be unique. It defaults to the name, so a job with no
    repeats never has to mention ids at all."""
    explicit = (device.get('id') or '').strip()
    if explicit:
        return explicit
    return (device.get('name') or '').strip()


def job_sections(job):
    """Section names in the order they should be laid out, top to bottom.

    An explicit "sections" list fixes the order; otherwise sections appear in
    the order their first device does. Devices with no section all land in one
    unnamed section, which is what an unsectioned job is."""
    order = []
    listed = job.get('sections')
    if isinstance(listed, list):
        for entry in listed:
            name = entry.get('name') if isinstance(entry, dict) else entry
            name = (name or '').strip()
            if name and name not in order:
                order.append(name)
    for device in job.get('devices') or []:
        if not isinstance(device, dict):
            continue
        name = (device.get('section') or '').strip()
        if name not in order:
            order.append(name)
    return order


def job_position(device, gx, gy, prefs=None):
    """Where a job device sits within its section, before sections are stacked.

    The y is the device's TOP edge, so devices written at the same y line up
    along their headers whatever their socket counts.

    ConnectCAD wires by horizontal alignment, so position is not decoration --
    it is how the schematic says what connects to what."""
    if prefs is None:
        prefs = PREF_DEFAULTS
    try:
        if device.get('x') is not None and device.get('y') is not None:
            return float(device['x']), float(device['y'])
    except (TypeError, ValueError):
        pass
    try:
        column = int(device.get('column') or 0)
    except (TypeError, ValueError):
        column = 0
    try:
        row = int(device.get('row') or 0)
    except (TypeError, ValueError):
        row = 0
    unit_x = gx if gx else 0.25
    unit_y = gy if gy else 0.25
    column_pitch = prefs.get('column_inches', JOB_COLUMN_INCHES)
    row_pitch = prefs.get('row_inches', JOB_ROW_INCHES)
    return (column * column_pitch / 0.25 * unit_x,
            -row * row_pitch / 0.25 * unit_y)


def job_socket_specs(device):
    """The job's sockets as the builder's (symbol, name, type, side) tuples."""
    specs = []
    for socket in device.get('sockets') or []:
        if not isinstance(socket, dict):
            continue
        name = (socket.get('name') or '').strip()
        if not name:
            continue
        side_text = (socket.get('side') or '').strip().upper()
        side = -1 if side_text.startswith('L') else 1
        symbol = 'skt_L' if side < 0 else 'skt_R'
        specs.append((symbol, name, (socket.get('type') or 'IO').upper(), side,
                      socket.get('signal') or '', socket.get('connector') or ''))
    return specs


def socket_stack_index(device, socket_name):
    """Where a named socket sits in its side's stack. Returns (index, side).

    Sockets are numbered down each edge independently, so the left and right
    stacks each start at 0."""
    wanted = (socket_name or '').strip().upper()
    counts = {}
    for socket in device.get('sockets') or []:
        if not isinstance(socket, dict):
            continue
        name = (socket.get('name') or '').strip()
        if not name:
            continue
        side = -1 if (socket.get('side') or '').strip().upper().startswith('L') else 1
        index = counts.get(side, 0)
        counts[side] = index + 1
        if name.upper() == wanted:
            return index, side
    return None, None


def stack_columns(devices, positions, upi, scale, gy, prefs, catalogue=None):
    """Stack each column by real device heights, so overlap cannot happen.

    ConnectCAD routes a circuit with elbows -- it does NOT need its two sockets
    at the same height. That was verified in a live drawing: three circuits
    from one device to three targets at three different heights all wired, and
    ConnectCAD drew each with a corner.

    So a fan-out belongs in ONE column, stacked. The plug-in places them,
    because it is the only party that knows how tall a device will be: the
    height depends on socket count, on any matching symbol, and on the grid.
    Asking a job's author to work that out is asking them to guess.

    Devices carrying align_to keep the position alignment gave them; everything
    else stacks in row order."""
    gap = prefs.get('device_gap_inches', PREF_DEFAULTS['device_gap_inches'])
    columns = {}
    for device in devices:
        if isinstance(device.get('align_to'), dict):
            continue          # its y is already decided
        # An explicit y is the job's own arrangement, worked out in the chat
        # and shown to the user in a preview before the file was handed over.
        # Overriding it here would make the preview a lie.
        if device.get('x') is not None and device.get('y') is not None:
            continue
        ident = job_device_id(device)
        if ident not in positions:
            continue
        columns.setdefault(round(positions[ident][0], 4), []).append(device)

    for _x, members in sorted(columns.items()):
        def row_of(device):
            try:
                return int(device.get('row') or 0)
            except (TypeError, ValueError):
                return 0
        members.sort(key=row_of)

        top = None
        for device in members:
            ident = job_device_id(device)
            x, y = positions[ident]
            if top is None:
                top = y            # the first device keeps where it was put
            else:
                y = top
            positions[ident] = (x, y)
            top = y - device_height(device, upi, scale, gy, catalogue) - gap


def align_within_section(devices, positions, upi, scale, gy):
    """Apply every align_to inside ONE section. Returns notes.

    ConnectCAD only wires sockets that sit at the same height, so a job whose
    y values are a few hundredths out draws a schematic with no circuits in
    it. Rather than ask whoever writes the job to do grid arithmetic in their
    head, a device says which of its sockets should line up with which socket
    on another device, and the y is computed from the same socket pitch the
    drawing code uses -- so the two cannot disagree.

    Alignment chains, so this resolves in dependency order and reports what it
    cannot resolve rather than silently leaving a device at the wrong height."""
    by_id = dict((job_device_id(d), d) for d in devices)
    notes = []

    pending = [i for i, d in by_id.items() if isinstance(d.get('align_to'), dict)]
    settled = set(by_id) - set(pending)

    while pending:
        progressed = []
        for ident in pending:
            device = by_id[ident]
            spec = device['align_to']
            target = (spec.get('device') or '').strip()
            if target not in by_id:
                notes.append('{}: align_to names "{}", which is not in this '
                             'section. Left where it was.'.format(ident, target))
                progressed.append(ident)
                continue
            if target not in settled:
                continue
            their_index, _s = socket_stack_index(by_id[target], spec.get('socket'))
            my_index, _s = socket_stack_index(device, spec.get('my_socket'))
            if their_index is None or my_index is None:
                missing = spec.get('socket') if their_index is None \
                    else spec.get('my_socket')
                notes.append('{}: align_to refers to socket "{}", which does '
                             'not exist. Left where it was.'.format(ident, missing))
                progressed.append(ident)
                continue
            x, _y = positions[ident]
            _tx, ty = positions[target]
            positions[ident] = (
                x,
                ty - socket_drop(their_index, upi, scale, gy)
                + socket_drop(my_index, upi, scale, gy))
            progressed.append(ident)

        if not progressed:
            for ident in pending:
                notes.append('{}: align_to cannot be resolved -- the chain it '
                             'is part of has no fixed starting point, or loops '
                             'back on itself. Left where it was.'.format(ident))
            break
        settled.update(progressed)
        pending = [i for i in pending if i not in progressed]
    return notes


def device_height(device, upi, scale, gy, catalogue=None):
    """How tall this device will be once drawn.

    A device matched to a SYMBOL takes the symbol's height: its sockets are
    already placed inside it, so the job usually lists none, and measuring the
    job's empty socket list would report a device far shorter than the one
    actually stamped out."""
    if catalogue:
        match = find_device_symbol(device.get('make') or '',
                                   device.get('model') or '', catalogue)
        if match and match.get('height'):
            return match['height']
    specs = job_socket_specs(device)
    if not specs:
        # Same precedence the builder uses, or a device whose sockets come from
        # a lookup gets measured as if it had none and the section below it
        # overlaps.
        make = device.get('make') or ''
        model = device.get('model') or ''
        entry = find_golden_device(make, model)
        if entry:
            specs = golden_socket_specs(entry)
        else:
            entry = find_db_device(make, model)
            if entry:
                specs = db_socket_specs(entry)
    return body_height_for(specs, upi, scale, gy)


def section_extent(devices, positions, upi, scale, gy, catalogue=None):
    """(top, bottom) of one section's devices, headers and bodies included."""
    top = None
    bottom = None
    for device in devices:
        _x, y = positions[job_device_id(device)]
        height = device_height(device, upi, scale, gy, catalogue)
        top = y if top is None else max(top, y)
        bottom = (y - height) if bottom is None else min(bottom, y - height)
    return (top or 0.0), (bottom or 0.0)


# ConnectCAD's signal vocabulary. A circuit carrying a signal the document does
# not define is flagged by ConnectCAD's own error checking after it is drawn,
# which is a bad way to find out.
#
# The shipped list is the floor, not the whole truth: a drawing can define its
# own, and the Geffen job uses MILAN PRI, MILAN SEC and MIDC, none of which
# ConnectCAD ships. So an unknown signal is reported as something to look at,
# never treated as an error on its own.
SIGNAL_TYPES_RELATIVE = os.path.join(
    'Libraries', 'Defaults', 'ConnectCAD', 'ConnectCAD_Database',
    'SignalTypes.txt')

_signal_cache = set()


def known_signals():
    """Every signal ConnectCAD ships, plus any the user has added."""
    if _signal_cache:
        return _signal_cache
    for base in ('/Applications/Vectorworks 2026',
                 os.path.expanduser('~/Library/Application Support/'
                                    'Vectorworks/2026')):
        path = os.path.join(base, SIGNAL_TYPES_RELATIVE)
        try:
            with open(path, 'rb') as f:
                raw = f.read().decode('utf-8-sig')
        except Exception:
            continue
        # The application and user copies disagree on line endings.
        raw = raw.replace('\r\n', '\n').replace('\r', '\n')
        for index, line in enumerate(raw.split('\n')):
            if index == 0 or not line.strip():
                continue          # row 0 is the header
            name = line.split('\t')[0].strip()
            if name:
                _signal_cache.add(name.upper())
    return _signal_cache


def unknown_signals(job):
    """Signals in a job that ConnectCAD does not ship a definition for.

    Returns an empty set when the signal list cannot be read at all, rather
    than reporting every signal as unknown -- a missing file is not evidence
    that a signal is wrong."""
    defined = known_signals()
    if not defined:
        return set()
    used = set()
    for circuit in job.get('circuits') or []:
        if isinstance(circuit, dict):
            signal = (circuit.get('signal') or '').strip()
            if signal:
                used.add(signal)
    for device in job.get('devices') or []:
        for socket in (device.get('sockets') or []):
            if isinstance(socket, dict):
                signal = (socket.get('signal') or '').strip()
                if signal:
                    used.add(signal)
    return set(s for s in used if s.upper() not in defined)


def layer_context_quietly():
    """The active layer's scale, units and grid, without writing to a log."""
    return active_layer_context([])


# How ConnectSelected actually pairs sockets, read out of
# connectCAD::ConnectSelected_EventSink::ConnectDevices (arm64 0x841e8):
#
#   * It contains NO floating-point comparison. Nothing is matched by height.
#   * Selected devices are grouped into COLUMNS by X-overlap of their bounding
#     boxes (Utilities::DoBoundsIntersectOnX, 0x1fce80). The test uses <=, so
#     boxes that merely touch count as the same column.
#   * If the selection resolves to only ONE column, the command skips wiring
#     entirely and silently activates an interactive tool instead. Nothing is
#     drawn and nothing is reported.
#   * Within a column, devices sort by bounding-box centre Y descending, and
#     sockets within a device by Y descending -- top to bottom.
#   * Pairing is then positional and first-free: the Nth source socket takes
#     the Nth still-free destination socket. The socket NAMES in a job are not
#     consulted.
#
# The last point is why a job must list a device's circuits in the same order
# as that device's sockets run down the page, and why the tool verifies what
# was actually created rather than trusting the command.
DEVICE_BODY_WIDTH_UNITS = 12          # 3 inches on a quarter-inch grid


def find_column_clashes(job, positions, gx):
    """Circuits whose two devices share an X band. Returns [(a, b, overlap)].

    ConnectSelected groups selected devices into columns by X-overlap and does
    nothing at all when everything lands in one column -- without an error, a
    dialog, or a trace in the drawing. A source sitting in the same X band as
    its destination is therefore a circuit that cannot be made, and finding
    that out afterwards means finding it out from an empty schematic."""
    width = DEVICE_BODY_WIDTH_UNITS * (gx or 0.25)
    seen = set()
    clashes = []
    for circuit in job.get('circuits') or []:
        if not isinstance(circuit, dict):
            continue
        a = (circuit.get('from') or {}).get('device')
        b = (circuit.get('to') or {}).get('device')
        if a not in positions or b not in positions or a == b:
            continue
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        a_left, a_right = positions[a][0] - width / 2.0, positions[a][0] + width / 2.0
        b_left, b_right = positions[b][0] - width / 2.0, positions[b][0] + width / 2.0
        # ConnectCAD's own test is <=, so touching counts as overlapping.
        if a_left <= b_right and b_left <= a_right:
            clashes.append((a, b, min(a_right, b_right) - max(a_left, b_left)))
    return clashes


def find_overlaps(job, positions, upi, scale, gy, catalogue=None):
    """Devices that would be drawn on top of one another. Returns [(a, b, by)].

    This is the trap in align_to, and it is arithmetic rather than a mistake
    anyone makes: sockets are one grid unit apart, but a device is at least
    three tall. Fan a switch out to eight speakers, align each to the next
    socket down, and put them all in one column, and consecutive speakers sit
    a quarter inch apart while being three quarters of an inch tall. They
    overlap by half an inch, every time.

    A schematic like that draws without complaint and then wires almost
    nothing, because ConnectCAD cannot route to a socket buried under another
    device."""
    boxes = []
    for device in job['devices']:
        if not isinstance(device, dict):
            continue
        ident = job_device_id(device)
        if ident not in positions:
            continue
        x, y = positions[ident]
        height = device_height(device, upi, scale, gy, catalogue)
        boxes.append((ident, (device.get('section') or '').strip(), x,
                      y, y - height))

    clashes = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a_id, a_sec, ax, a_top, a_bot = boxes[i]
            b_id, b_sec, bx, b_top, b_bot = boxes[j]
            if a_sec != b_sec or abs(ax - bx) > 0.01:
                continue
            depth = min(a_top, b_top) - max(a_bot, b_bot)
            if depth > 0.001:
                clashes.append((a_id, b_id, depth))
    return clashes


def resolve_job_positions(job, gx, gy, upi=1.0, scale=1.0, prefs=None,
                          catalogue=None):
    """Where every device goes. Returns ({id: (x, y)}, notes).

    Sections are laid out as horizontal BANDS down the same design layer, which
    is how these drawings are actually organised: analog, power and speaker
    each get their own region of one "Schematic" layer, and sheet viewports
    crop them onto separate drawings.

    Each section is resolved independently against its own origin, then the
    bands are stacked with a gap. That ordering matters -- a section's depth is
    not known until its alignment is resolved, so the stacking cannot happen
    first."""
    if prefs is None:
        prefs = load_prefs()

    by_section = {}
    for device in job['devices']:
        if not isinstance(device, dict):
            continue
        by_section.setdefault((device.get('section') or '').strip(),
                              []).append(device)

    positions = {}
    notes = []
    for device in job['devices']:
        if isinstance(device, dict):
            positions[job_device_id(device)] = job_position(device, gx, gy, prefs)

    gap = prefs.get('section_gap_inches', PREF_DEFAULTS['section_gap_inches'])
    running_top = 0.0
    for section in job_sections(job):
        devices = by_section.get(section)
        if not devices:
            continue
        # Stack first, then align: a device pinned by align_to must not be
        # shoved by the stacker, and the stacker needs the others settled
        # before it can measure the section.
        stack_columns(devices, positions, upi, scale, gy, prefs, catalogue)
        notes.extend(align_within_section(devices, positions, upi, scale, gy))

        top, bottom = section_extent(devices, positions, upi, scale, gy,
                                     catalogue)
        shift = running_top - top
        if shift:
            for device in devices:
                ident = job_device_id(device)
                x, y = positions[ident]
                positions[ident] = (x, y + shift)
        running_top = (bottom + shift) - gap
    return positions, notes


def build_job_devices(job, log, upi, scale, grid):
    """Create every device in the job. Returns {name: handle}.

    A matching device symbol is preferred over building by hand: it needs no
    layout and reproduces a device somebody already drew correctly."""
    gx, gy = grid if grid else (None, None)
    catalogue = device_symbol_catalogue()
    prefs = load_prefs()
    made = {}

    positions, notes = resolve_job_positions(job, gx, gy, upi, scale, prefs,
                                             catalogue)
    for note in notes:
        log.append('  WARN    {}'.format(note))

    current_section = None
    for device in job['devices']:
        name = (device.get('name') or '').strip()
        ident = job_device_id(device)
        tag = (device.get('tag') or name).strip()
        make = device.get('make') or ''
        model = device.get('model') or ''
        x, y = positions.get(ident) or job_position(device, gx, gy, prefs)

        section = (device.get('section') or '').strip()
        if section != current_section:
            current_section = section
            log.append('  ---- section: {}'.format(section or '(unsectioned)'))

        match = find_device_symbol(make, model, catalogue)
        if match:
            handle = place_device_from_symbol(match['handle'], x, y, name, tag)
            if handle:
                made[ident] = handle
                log.append('  symbol  {:<30} from {}'.format(
                    name[:30], match['symbol']))
                continue
            log.append('  WARN    {:<30} symbol {} would not place'.format(
                name[:30], match['symbol']))

        # Precedence, and the reason for it:
        #   1. a device symbol   -- somebody drew it correctly, sockets placed
        #   2. the job's sockets -- the circuits reference THESE names, so
        #                           overriding them would break the wiring
        #   3. the database      -- real connectors, for a device the job
        #                           described but did not detail
        specs = job_socket_specs(device)
        source = 'job'
        if not specs:
            # The curated list first: it is the one place house convention is
            # pinned down, and it is the same file Claude read when it wrote
            # the job, so the socket names on both sides agree by construction.
            entry = find_golden_device(make, model)
            if entry:
                specs = golden_socket_specs(entry)
                source = 'curated list'
                log.append('  golden  {:<30} {} / {}: {} socket(s)'.format(
                    name[:30], entry['make'], entry['model'], len(specs)))
                log.append('          sockets: {}'.format(
                    ', '.join(s[1] for s in specs[:16])
                    + (' ...' if len(specs) > 16 else '')))
        if not specs:
            entry = find_db_device(make, model)
            if entry:
                specs = db_socket_specs(entry)
                source = 'database'
                log.append('  db      {:<30} {} / {}: {} socket(s)'.format(
                    name[:30], entry['make'], entry['model'], len(specs)))
                # The job's circuits cannot reference names it never saw, so
                # the names are logged rather than left to be discovered when
                # nothing wires.
                log.append('          sockets: {}'.format(
                    ', '.join(s[1] for s in specs[:16])
                    + (' ...' if len(specs) > 16 else '')))
        if not specs:
            log.append('  WARN    {:<30} no symbol, no sockets listed, and in '
                       'neither the curated list nor the device '
                       'database'.format(name[:30]))
        handle, ok = build_device(name, tag, make, model, x, y, specs, log,
                                  upi, scale, grid,
                                  device.get('description') or '')
        if handle:
            made[ident] = handle
            log.append('  built   {:<30} {} socket(s) from the {}{}'.format(
                name[:30], len(specs), source,
                '' if ok else '  (some sockets failed)'))
        else:
            log.append('  FAIL    {:<30} could not be created'.format(name[:30]))
    return made


# Circuit fields worth setting on a generated circuit. Confirmed against a
# real drawing's field dump -- note ConnectCAD's own field names, which are
# plain words here and underscored elsewhere on the same record.
CIRCUIT_SIGNAL_FIELD = 'Signal'
CIRCUIT_CABLE_FIELD = 'Cable'        # human-readable cable name, drawn mid-line
CIRCUIT_LABEL_FIELD = 'Label'
CIRCUIT_TYPE_FIELD = 'CircuitType'   # line routing mode; a real job uses 'rounded'


# ConnectCAD files every circuit in a class named after its signal. The prefix
# is the resource string "CC-Circuit-Signal" from ConnectCADClasses.vwstrings,
# whose own comment reads "Must be the same as the class name in all ConnectCAD
# default content!" -- so it is fixed, not localised.
#
# These classes are how a schematic gets divided: a sheet viewport showing only
# CC-Circuit-Signal-LINE is the analog drawing. Getting the class wrong does not
# look wrong on the design layer, it silently empties a sheet.
CIRCUIT_SIGNAL_CLASS_PREFIX = 'CC-Circuit-Signal'


def signal_class_name(signal):
    """The class a circuit of this signal belongs in, or '' for no signal."""
    signal = (signal or '').strip()
    if not signal:
        return ''
    return '{}-{}'.format(CIRCUIT_SIGNAL_CLASS_PREFIX, signal)


def ensure_class(name):
    """Make sure a class exists, leaving the active class as it was.

    NameClass creates the class if it is missing AND makes it active, so the
    previous active class has to be put back -- otherwise every object drawn
    afterwards silently lands in the last class this touched. Creating a class
    that already exists is a no-op, so there is no need to test first."""
    if not name:
        return False
    previous = ''
    try:
        previous = vs.ActiveClass() or ''
    except Exception:
        pass
    try:
        vs.NameClass(name)
    except Exception:
        return False
    finally:
        if previous and previous != name:
            try:
                vs.NameClass(previous)
            except Exception:
                pass
    return True


def apply_signal_class(handle, signal):
    """Put a circuit in the class its signal calls for. Returns True if set.

    WHY THIS IS NEEDED, rather than left to ConnectCAD: the automatic classing
    lives in the circuit's reset handler but is gated on the hidden __Version
    parameter -- it runs only while __Version <= 2599, and the reset then
    stamps 2600. ConnectSelected creates the circuit AND resets it, so by the
    time a signal is written from script that gate has already closed and the
    circuit keeps the class it was given for its default signal.

    Changing the signal in the Object Info palette DOES reclass, because the
    OIP value-transfer path does it separately -- which is why this looks
    automatic when you do it by hand and is not when a script does it."""
    name = signal_class_name(signal)
    if not name:
        return False
    if not ensure_class(name):
        return False
    try:
        vs.SetClass(handle, name)
        return True
    except Exception:
        return False


# Where a circuit turns. ConnectCAD routes with elbows, and by default every
# circuit leaving one device turns at the same distance out -- so a fan-out to a
# stacked column draws all its vertical runs on top of each other.
#
# The real drawing staggers them. Two circuits from SWTCH 4.01, on LAN 2 and
# LAN 3, carry ControlPoint03X of 0.75" and 2.625" respectively: the elbow sits
# further out for the second, so the drops do not coincide.
#
# INFERRED, from two samples: ControlPoint03X is the distance from the SOURCE
# socket to the elbow, and ControlPoint02X the matching distance back from the
# destination. The drawing's own values are consistent with that reading and
# with nothing else obvious, but it has not been confirmed against the binary.
# Setting circuit_stagger_inches to 0 turns this off and leaves ConnectCAD's
# own routing alone.
CIRCUIT_ELBOW_FIELD = 'ControlPoint03X'


def stagger_circuit(handle, index, prefs, upi):
    """Push this circuit's elbow further out than the one before it.

    `index` counts circuits leaving the same device, so the first keeps the
    default and each after it turns a little further along."""
    step = prefs.get('circuit_stagger_inches',
                     PREF_DEFAULTS['circuit_stagger_inches'])
    if not step or index <= 0:
        return False
    # Document units, like every other length ConnectCAD stores.
    offset = (index + 1) * step * (upi or 1.0)
    field = resolve_field(handle, [CIRCUIT_ELBOW_FIELD]) or CIRCUIT_ELBOW_FIELD
    return write_field(handle, field, '{:g}'.format(offset))


def finish_circuit(handle, circuit, prefs, elbow_index=0, upi=1.0):
    """Write the job's own values onto a circuit ConnectSelected just made.

    ConnectCAD derives a circuit's endpoints from the sockets it joined, but
    NOT its signal: a real drawing carries socket signal 'LAN' on a circuit
    whose own signal is 'MILAN PRI'. So a generated circuit keeps whatever
    default it was given unless the job says otherwise, which is why this
    exists.

    The Number field is deliberately NOT touched. ConnectCAD numbers wires
    itself, by signal type; writing our own numbers would fight it and produce
    two competing schemes in one drawing.

    Returns the fields it actually wrote."""
    written = []
    values = [
        (CIRCUIT_SIGNAL_FIELD, (circuit.get('signal') or '').strip()),
        (CIRCUIT_CABLE_FIELD, (circuit.get('cable') or '').strip()),
        (CIRCUIT_LABEL_FIELD, (circuit.get('label') or '').strip()),
    ]

    line_mode = (prefs.get('circuit_type') or '').strip()
    if line_mode:
        # Never convert an arrow circuit. Arrows are paired stubs joined by
        # __Arrow_ID rather than one routed line, so overwriting the field
        # leaves the pair half-converted rather than re-routing anything.
        existing = read_field(handle, resolve_field(handle, [CIRCUIT_TYPE_FIELD])
                              or CIRCUIT_TYPE_FIELD)
        if existing != CIRCUIT_TYPE_ARROW:
            values.append((CIRCUIT_TYPE_FIELD, line_mode))

    for field, value in values:
        if not value:
            continue
        resolved = resolve_field(handle, [field]) or field
        if write_field(handle, resolved, value):
            written.append(field)
    if written:
        try:
            vs.ResetObject(handle)
        except Exception:
            pass

    # AFTER the reset, deliberately. Reset is what would re-class the circuit
    # if it still could, so setting the class first would be undone.
    signal = (circuit.get('signal') or '').strip()
    if signal and apply_signal_class(handle, signal):
        written.append('class')

    if stagger_circuit(handle, elbow_index, prefs, upi):
        written.append('elbow')
        try:
            vs.ResetObject(handle)
        except Exception:
            pass
    return written


def wire_job(job, made, log):
    """Wire the job's circuits, then report which ones actually took.

    ConnectSelected joins every aligned socket pair between two devices at
    once, so it is run once per device PAIR rather than once per circuit.
    Whether a circuit exists afterwards is decided by reading the association
    back -- the command returning cleanly proves nothing.

    Verification COUNTS rather than matching one-to-one. Circuits in the
    drawing record device NAMES, and the same physical device is drawn again in
    each section it appears in, so a name can identify two different blocks. If
    a job asks for two circuits that both read back as
    "SPK 1.01 / LAN_IN 1 -> SWTCH 4.01 / LAN 1", finding one of them is not
    enough; finding two is. Matching on identity alone would call the second
    one wired because the first exists."""
    circuits = job.get('circuits') or []
    if not circuits:
        return 0, []

    names = {}
    for device in job['devices']:
        if isinstance(device, dict):
            names[job_device_id(device)] = (device.get('name') or '').strip()

    pairs = []
    for circuit in circuits:
        source = (circuit.get('from') or {}).get('device')
        destination = (circuit.get('to') or {}).get('device')
        if source in made and destination in made:
            key = (source, destination)
            if key not in pairs:
                pairs.append(key)

    command = getattr(vs, 'DoMenuTextByName', None)
    if command is None:
        log.append('  FAIL  DoMenuTextByName unavailable; nothing wired')
        return 0, [(c, 'no way to run ConnectSelected') for c in circuits]

    for source, destination in pairs:
        try:
            vs.DSelectAll()
            vs.SetSelect(made[source])
            vs.SetSelect(made[destination])
            command('ConnectSelected', 0)
        except Exception as err:
            log.append('  WARN  wiring {} -> {} raised: {}'.format(
                source, destination, err))
    try:
        vs.DSelectAll()
    except Exception:
        pass

    def endpoint_key(a_dev, a_skt, b_dev, b_skt):
        """Order-independent, so a circuit read back the other way still matches."""
        return tuple(sorted([(a_dev or '', a_skt or ''), (b_dev or '', b_skt or '')]))

    # What exists now, read from the stored associations. Handles are kept, not
    # just counted, because each job circuit's signal, wire number and cable
    # name still have to be written onto the object ConnectSelected made.
    actual = {}
    for handle in walk_document():
        if classify(handle) != 'circuit':
            continue
        source, destination = circuit_endpoints(handle)
        if not source or not destination:
            continue
        key = endpoint_key(source.get('device'), source.get('socket'),
                           destination.get('device'), destination.get('socket'))
        actual.setdefault(key, []).append(handle)

    prefs = load_prefs()
    upi = units_per_inch()[0]
    # How many circuits have already left this device, so each one after the
    # first turns a little further out and the drops do not coincide.
    leaving = {}
    missing = []
    finished = 0
    staggered = 0
    for circuit in circuits:
        source = circuit.get('from') or {}
        destination = circuit.get('to') or {}
        key = endpoint_key(names.get(source.get('device')), source.get('socket'),
                           names.get(destination.get('device')),
                           destination.get('socket'))
        found = actual.get(key)
        if found:
            # Spend it, so a second identical-looking circuit needs a second
            # real one rather than matching the same object twice.
            handle = found.pop(0)
            origin = source.get('device')
            index = leaving.get(origin, 0)
            leaving[origin] = index + 1
            written = finish_circuit(handle, circuit, prefs, index, upi)
            if written:
                finished += 1
            if 'elbow' in written:
                staggered += 1
        else:
            missing.append((circuit, 'no circuit found between these sockets'))

    if finished:
        log.append('  {} circuit(s) given their signal and cable name'.format(
            finished))
    if staggered:
        log.append('  {} circuit(s) had their elbow moved so parallel runs do '
                   'not overlap'.format(staggered))
    return len(circuits) - len(missing), missing


def tool_draw_job():
    """Returns (status, summary)."""
    path, note = pick_job_file()
    if path is None:
        if note:
            vs.AlrtDialog(note)
            return 'stopped', note
        return 'cancelled', None

    job, problems = read_job(path)
    if problems and job is None:
        vs.AlrtDialog('Cannot draw the job:\n\n{}'.format('\n'.join(problems[:12])))
        return 'stopped', None
    if problems:
        detail = '\n'.join('  ' + p for p in problems[:10])
        if vs.AlertQuestion(
                'The job has {} problem(s).'.format(len(problems)),
                '{}\n\nDraw the rest anyway?'.format(detail),
                0, 'Draw anyway', 'Cancel', '', '') != 1:
            return 'cancelled', 'job has problems; nothing drawn'

    devices = job['devices']
    circuits = job.get('circuits') or []

    # Checked BEFORE the confirmation, so a job that cannot work is refused
    # rather than drawn and then explained.
    _layer, pre_scale, pre_upi, pre_grid = layer_context_quietly()
    positions, _notes = resolve_job_positions(
        job, pre_grid[0], pre_grid[1], pre_upi, pre_scale, load_prefs(),
        device_symbol_catalogue())
    clashes = find_overlaps(job, positions, pre_upi, pre_scale, pre_grid[1],
                            device_symbol_catalogue())
    if clashes:
        listing = '\n'.join('   {} and {} overlap by {:.2f}"'.format(*c)
                             for c in clashes[:8])
        if len(clashes) > 8:
            listing += '\n   ... and {} more'.format(len(clashes) - 8)
        if vs.AlertQuestion(
                '{} pair(s) of devices would be drawn on top of each '
                'other.'.format(len(clashes)),
                '{}\n\nConnectCAD cannot route to a socket buried under '
                'another device, so most circuits will not wire. This usually '
                'means several devices share a column while being aligned one '
                'socket apart -- they need a column each.\n\nDraw it '
                'anyway?'.format(listing),
                1, 'Draw anyway', 'Cancel', '', '') != 1:
            return 'stopped', '{} overlapping device pair(s)'.format(len(clashes))

    column_clashes = find_column_clashes(job, positions, pre_grid[0])
    if column_clashes:
        listing = '\n'.join('   {} and {} share an X band'.format(a, b)
                             for a, b, _o in column_clashes[:8])
        if len(column_clashes) > 8:
            listing += '\n   ... and {} more'.format(len(column_clashes) - 8)
        if vs.AlertQuestion(
                '{} circuit(s) join devices that overlap horizontally.'.format(
                    len(column_clashes)),
                '{}\n\nConnectCAD groups devices into columns by horizontal '
                'overlap and refuses to wire a selection that is all one '
                'column -- silently, with no error. These circuits cannot be '
                'made until the devices are moved into separate columns.\n\n'
                'Draw it anyway?'.format(listing),
                1, 'Draw anyway', 'Cancel', '', '') != 1:
            return 'stopped', '{} circuit(s) join overlapping columns'.format(
                len(column_clashes))

    unknown = unknown_signals(job)
    if unknown:
        if vs.AlertQuestion(
                '{} signal(s) are not defined in ConnectCAD.'.format(len(unknown)),
                '{}\n\nCircuits carrying a signal this document does not know '
                'about will be flagged by ConnectCAD after they are drawn. '
                'Either define them in ConnectCAD Settings first, or change '
                'them in the job.\n\nDraw it anyway?'.format(
                    '   ' + ', '.join(sorted(unknown)[:12])),
                1, 'Draw anyway', 'Cancel', '', '') != 1:
            return 'stopped', 'undefined signals: {}'.format(
                ', '.join(sorted(unknown)[:6]))

    if vs.AlertQuestion(
            'Draw {} device(s) and {} circuit(s)?'.format(
                len(devices), len(circuits)),
            'They will be created on the active layer. Undo afterwards if the '
            'result is not what you wanted.',
            0, 'Draw it', 'Cancel', '', '') != 1:
        return 'cancelled', None

    log = ['SCHEMATIC JOB', '', 'Job file: {}'.format(path), '']
    try:
        vs.PushAttrs()
    except Exception:
        pass
    _layer, scale, upi, grid = active_layer_context(log)
    log.append('')

    log.append('Devices')
    made = build_job_devices(job, log, upi, scale, grid)
    log.append('')

    log.append('Wiring')
    wired, missing = wire_job(job, made, log)
    log.append('  {} of {} circuit(s) wired'.format(wired, len(circuits)))
    for circuit, why in missing[:15]:
        source = (circuit.get('from') or {}).get('device')
        destination = (circuit.get('to') or {}).get('device')
        log.append('  NOT WIRED  {} -> {}: {}'.format(source, destination, why))
    if len(missing) > 15:
        log.append('  ... and {} more'.format(len(missing) - 15))

    try:
        vs.PopAttrs()
    except Exception:
        pass
    reset = reset_circuits()
    log.append('')
    log.append('Circuits reset: {}'.format(reset))

    path = save_text('schematic_job_report',
                     '\n'.join(report_header('SCHEMATIC JOB') + log))
    summary = '{} of {} device(s), {} of {} circuit(s)'.format(
        len(made), len(devices), wired, len(circuits))
    if missing:
        summary += '\n{} circuit(s) not wired - see the report'.format(len(missing))
    vs.AlrtDialog('{}\n\nReport:\n{}'.format(summary, path))
    return 'done', '{}\n{}'.format(summary, path)


# ═══════════════════════════════════════════════════════════════════════════
# LAUNCHER
# ═══════════════════════════════════════════════════════════════════════════
lToolLbl = 304
lDumpChk, lNormChk, lMatchChk, lSpellChk = 305, 306, 307, 310
lRefChk = 311
lProbeChk = 312
lPromptChk, lJobChk = 313, 314
lPrefsChk, lSetupLbl = 315, 316
lSearchChk, lReplaceChk = 317, 318
lOrderTxt, lHintTxt = 308, 309


def ask_which_tools():
    """Pick one or more tools. Returns a list of TOOL_* constants, or None.

    The list comes back in RUN order, not tick order -- see run_cc_tools."""
    chosen = {}
    dlg = vs.CreateLayout('CC Tools', False, 'Continue', 'Cancel')

    # Two groups: the tools used while drafting, and the ones used when
    # setting a drawing up or working out why something went wrong. The second
    # group is where a tool goes when it is not part of anyone's daily work.
    vs.CreateStaticText(dlg, lToolLbl, 'Drafting:', -1)
    vs.CreateCheckBox(dlg, lNormChk, 'Normalise Names  (uppercase / trim)')
    vs.CreateCheckBox(dlg, lMatchChk, 'Match Names and Display Tags')
    vs.CreateCheckBox(dlg, lSpellChk, 'Spell Check')
    vs.CreateCheckBox(dlg, lSearchChk, 'Search ConnectCAD Objects  (read-only)')
    vs.CreateCheckBox(dlg, lReplaceChk, 'Find and Replace  (writes)')
    vs.CreateCheckBox(dlg, lJobChk, 'Draw schematic job  (writes)')

    vs.CreateStaticText(dlg, lSetupLbl, 'Setup and diagnostics:', -1)
    vs.CreateCheckBox(dlg, lPrefsChk, 'Preferences  (spacing, circuit line mode)')
    vs.CreateCheckBox(dlg, lPromptChk, 'Export prompt for Claude')
    vs.CreateCheckBox(dlg, lDumpChk, 'Dump Fields  (read-only)')
    vs.CreateCheckBox(dlg, lRefChk, 'Export Reference Schematic  (read-only)')
    vs.CreateCheckBox(dlg, lProbeChk, 'Creation Probe  (writes - scratch file only)')

    vs.CreateStaticText(
        dlg, lOrderTxt,
        'Run in this order. Preferences are saved first, so a job drawn in\n'
        'the same run uses them. Normalising before Match resolves case- and\n'
        'space-only mismatches, so Match only asks about genuinely different\n'
        'pairs, and Spell Check then sees the settled spelling of every name.', -1)
    vs.CreateStaticText(
        dlg, lHintTxt, 'Reports are written to ~/Documents/CC Tools/', -1)

    vs.SetFirstLayoutItem(dlg, lToolLbl)
    vs.SetBelowItem(dlg, lToolLbl, lNormChk, 0, 0)
    vs.SetBelowItem(dlg, lNormChk, lMatchChk, 0, 0)
    vs.SetBelowItem(dlg, lMatchChk, lSpellChk, 0, 0)
    vs.SetBelowItem(dlg, lSpellChk, lSearchChk, 0, 0)
    vs.SetBelowItem(dlg, lSearchChk, lReplaceChk, 0, 0)
    vs.SetBelowItem(dlg, lReplaceChk, lJobChk, 0, 0)
    vs.SetBelowItem(dlg, lJobChk, lSetupLbl, 0, 10)
    vs.SetBelowItem(dlg, lSetupLbl, lPrefsChk, 0, 0)
    vs.SetBelowItem(dlg, lPrefsChk, lPromptChk, 0, 0)
    vs.SetBelowItem(dlg, lPromptChk, lDumpChk, 0, 0)
    vs.SetBelowItem(dlg, lDumpChk, lRefChk, 0, 0)
    vs.SetBelowItem(dlg, lRefChk, lProbeChk, 0, 0)
    vs.SetBelowItem(dlg, lProbeChk, lOrderTxt, 0, 10)
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
            vs.SetBooleanItem(dlg, lPromptChk, False)
            vs.SetBooleanItem(dlg, lJobChk, False)
            vs.SetBooleanItem(dlg, lPrefsChk, False)
            vs.SetBooleanItem(dlg, lSearchChk, False)
            vs.SetBooleanItem(dlg, lReplaceChk, False)
        elif item == kOK:
            picked = []
            # Fixed order, independent of which boxes the user ticked first.
            # Preferences lead: ticking them alongside Draw schematic job
            # should mean the job is drawn with the settings just saved.
            if vs.GetBooleanItem(dlg, lPrefsChk):
                picked.append(TOOL_PREFS)
            if vs.GetBooleanItem(dlg, lSearchChk):
                picked.append(TOOL_SEARCH)
            if vs.GetBooleanItem(dlg, lReplaceChk):
                picked.append(TOOL_REPLACE)
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
            if vs.GetBooleanItem(dlg, lPromptChk):
                picked.append(TOOL_PROMPT)
            if vs.GetBooleanItem(dlg, lJobChk):
                picked.append(TOOL_JOB)
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
    (TOOL_PROMPT, 'Export prompt'),
    (TOOL_JOB, 'Draw schematic job'),
    (TOOL_PREFS, 'Preferences'),
    (TOOL_SEARCH, 'Search'),
    (TOOL_REPLACE, 'Find and Replace'),
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
        TOOL_PROMPT: tool_export_prompt,
        TOOL_JOB: tool_draw_job,
        TOOL_PREFS: tool_preferences,
        TOOL_SEARCH: tool_search,
        TOOL_REPLACE: tool_find_replace,
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
