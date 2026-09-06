# Remove the TEST devices and their circuits from a scratch drawing.
#
# A ONE-OFF, not part of CC Tools. Paste into Plug-in Manager > New > Command
# (Python), run it, then delete the command again. It is deliberately not in
# the plug-in: a tool that deletes objects by name prefix is a bad thing to
# leave sitting in a menu next to the drafting tools.
#
# It removes only objects whose device name begins with PREFIX, reports exactly
# what it found, and asks before deleting anything.

import vs

PREFIX = 'TEST'

TYPE_GROUP = 11
TYPE_PIO = 86


def pio_name(handle):
    record = vs.GetParametricRecord(handle)
    return (vs.GetName(record) or '') if record else ''


def read(handle, field):
    name = pio_name(handle)
    if not name:
        return ''
    return vs.GetRField(handle, name, field) or ''


def walk(container, out, depth=0):
    """Every object on the layer, descending into groups and plug-in objects."""
    if depth > 6:
        return
    handle = vs.FInGroup(container) if depth else vs.FIn3D(container)
    while handle:
        out.append(handle)
        if vs.GetTypeN(handle) in (TYPE_GROUP, TYPE_PIO):
            walk(handle, out, depth + 1)
        handle = vs.NextObj(handle)


def everything():
    out = []
    layer = vs.FLayer()
    while layer:
        walk(layer, out)
        layer = vs.NextLayer(layer)
    return out


def kind(handle):
    if vs.GetTypeN(handle) != TYPE_PIO:
        return ''
    return pio_name(handle).lower().replace(' ', '')


def run():
    devices = []
    circuits = []

    for handle in everything():
        what = kind(handle)
        if what == 'device':
            name = read(handle, 'name')
            if name.startswith(PREFIX):
                devices.append((handle, name))
        elif what == 'circuit':
            # Circuits cache both endpoint names, so either end matching is
            # enough -- a circuit with one TEST end would be left dangling.
            ends = [read(handle, 'Src_Dev_Name'), read(handle, 'Dst_Dev_Name')]
            if any(e.startswith(PREFIX) for e in ends):
                circuits.append((handle, ' -> '.join(e or '?' for e in ends)))

    if not devices and not circuits:
        vs.AlrtDialog('Nothing found whose name starts with "{}".'.format(PREFIX))
        return

    listing = '\n'.join(
        ['{} device(s):'.format(len(devices))]
        + ['   ' + n for _h, n in devices[:12]]
        + (['   ... and {} more'.format(len(devices) - 12)] if len(devices) > 12 else [])
        + ['', '{} circuit(s):'.format(len(circuits))]
        + ['   ' + n for _h, n in circuits[:12]]
        + (['   ... and {} more'.format(len(circuits) - 12)] if len(circuits) > 12 else []))

    if vs.AlertQuestion('Delete everything named "{}..."?'.format(PREFIX),
                        listing, 0, 'Delete', 'Cancel', '', '') != 1:
        return

    # Circuits first: deleting a device out from under a circuit can leave the
    # circuit holding a stale endpoint that then resists deletion.
    removed = 0
    for handle, _name in circuits + devices:
        try:
            vs.DelObject(handle)
            removed += 1
        except Exception:
            pass

    vs.AlrtDialog('Deleted {} object(s):\n{} circuit(s), {} device(s).'.format(
        removed, len(circuits), len(devices)))


run()
