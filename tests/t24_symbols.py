"""Device-symbol tests.

A device symbol holds a fully-built Device with its sockets already placed, so
stamping one needs no layout at all -- no grid, no pitch, no header baseline.
It also matches house style by construction, because the symbol came from a
device somebody drew by hand.
"""
from harness import Doc, Obj, Results, load, dev, sock

R = Results()
check = R.check


def device_in_symbol(name, make, model, sockets=2):
    """A symbol definition containing one built Device."""
    body = Obj('Rect', {})
    kids = [body] + [sock('IO %d' % i) for i in range(sockets)]
    device = Obj('Device', {'name': name, 'tag': name, 'make': make,
                            'model': model, 'type': 'Generic'}, children=kids)
    return Obj('SymDef', {}, children=[device]), device


symdef, inner = device_in_symbol('TEMPLATE', 'Meyer Sound', 'Galaxy 408', 3)
other, _o = device_in_symbol('OTHER', 'Cisco', 'C9300', 2)
plain = Obj('SymDef', {}, children=[Obj('Rect', {})])       # not a device symbol

m, vs = load(Doc([[dev('x')]]))
vs.FInSymDef = lambda s: s.children[0] if s.children else None
vs.GetCustomObjectProfileGroup = lambda h: h
# ConnectCAD files real device symbols in 'zConnectCAD db Created'. The root
# holds device PARTS -- jacks, terminals -- which are Device PIOs too, so a
# root-only search finds the wrong things and misses the right ones.
part, _p = device_in_symbol('AudJack2FN', '', '', 2)
FOLDERS = {
    'zConnectCAD db Created': [('Meyer Sound_Galaxy 408', symdef),
                               ('Cisco_C9300', other)],
    'ConnectCAD Devices': [],
    '': [('AudJack2FN', part), ('A Plain Symbol', plain)],
}
lists = {}


def build(t, f, sub):
    entries = FOLDERS.get(sub, [])
    lists[len(lists) + 1] = entries
    return len(lists), len(entries)


vs.BuildResourceList = build
vs.GetNameFromResourceList = lambda lid, i: lists[lid][i - 1][0]
vs.GetResourceFromList = lambda lid, i: lists[lid][i - 1][1]

# ── T1: the Device inside a symbol definition is found ──────────────────────
check('T1 device found inside a symbol', m.device_pio_in_symbol(symdef) is inner)
check('T1 a plain symbol yields nothing', m.device_pio_in_symbol(plain) is None)
check('T1 no symbol yields nothing', m.device_pio_in_symbol(None) is None)

# ── T2: the catalogue reports what each symbol is a device OF ───────────────
catalogue = m.device_symbol_catalogue()
check('T2 non-device symbols excluded',
      all(c['symbol'] != 'A Plain Symbol' for c in catalogue),
      repr([c['symbol'] for c in catalogue]))
# Look up by name: the catalogue is sorted, so position is not identity.
first = next(c for c in catalogue if c['symbol'] == 'Meyer Sound_Galaxy 408')
check('T2 make and model read from the Device, not the name',
      first['make'] == 'Meyer Sound' and first['model'] == 'Galaxy 408',
      repr(first))
check('T2 socket count reported', first['sockets'] == 3, repr(first))

# ── T3: matching is forgiving about how a model is written ─────────────────
check('T3 exact make and model match',
      m.find_device_symbol('Meyer Sound', 'Galaxy 408', catalogue) is first)
check('T3 case and separators ignored',
      m.find_device_symbol('MEYER SOUND', 'GALAXY-408', catalogue) is first)
check('T3 underscores ignored',
      m.find_device_symbol('meyer_sound', 'galaxy_408', catalogue) is first)
check('T3 model alone still matches',
      m.find_device_symbol('', 'Galaxy 408', catalogue) is first)
check('T3 a make alone is never enough',
      m.find_device_symbol('Meyer Sound', '', catalogue) is None)
check('T3 an unknown model finds nothing',
      m.find_device_symbol('Meyer Sound', 'X-800', catalogue) is None)

# ── T4: stamping copies the Device, sockets and all ─────────────────────────
m4, vs4 = load(Doc([[dev('x')]]))
vs4.FInSymDef = lambda s: s.children[0] if s.children else None
duplicated = []


def duplicate(proto, container):
    copy = Obj(proto.record, dict(proto.fields), children=list(proto.children))
    duplicated.append(copy)
    return copy


vs4.CreateDuplicateObject = duplicate
vs4.GetBBox = lambda h: (-1.5, 0.4, 1.5, -1.0)
moves = []
vs4.HMove = lambda h, dx, dy: moves.append((round(dx, 3), round(dy, 3)))
vs4.NumRecords = lambda h: 0

placed = m4.place_device_from_symbol(symdef, 10.0, 5.0, 'AMP 1', 'AMP 1')
check('T4 a device was stamped', placed is not None and placed in duplicated)
check('T4 its sockets came with it', len(placed.children) == 4,
      repr([c.record for c in placed.children]))
check('T4 named after stamping', placed.fields['name'] == 'AMP 1', repr(placed.fields))
check('T4 tagged after stamping', placed.fields['tag'] == 'AMP 1')
check('T4 make and model preserved from the symbol',
      placed.fields['make'] == 'Meyer Sound' and placed.fields['model'] == 'Galaxy 408',
      repr(placed.fields))
# (x, y) places the device's TOP EDGE at y, centred on x, so a row of devices
# lines up along its tops regardless of how tall each one is.
check('T4 centred on x, top edge at y',
      moves and moves[-1] == (10.0, 4.6), repr(moves))

# ── T5: no layout is computed when stamping ────────────────────────────────
# The whole point: a symbol already has its sockets placed, so none of the
# grid, pitch or header rules are consulted.
consulted = []
m4.place_socket = lambda *a, **k: consulted.append('place_socket')
m4.socket_drop = lambda *a, **k: consulted.append('socket_drop')
m4.place_device_from_symbol(symdef, 0, 0, 'B', 'B')
check('T5 stamping computes no socket geometry', consulted == [], repr(consulted))

# ── T6: a symbol with no Device inside is refused ──────────────────────────
check('T6 a plain symbol cannot be stamped',
      m4.place_device_from_symbol(plain, 0, 0) is None)


# ── T7: devices come from ConnectCAD's folder, parts from the root ─────────
# The root of the Resource Manager holds device PARTS -- jacks, terminals,
# patch points -- which are Device plug-in objects too. Searching only the root
# returns those and misses every real device.
check('T7 ConnectCAD device folder is searched first',
      m.DEVICE_SYMBOL_FOLDERS[0] == 'zConnectCAD db Created',
      repr(m.DEVICE_SYMBOL_FOLDERS))

catalogue7 = m.device_symbol_catalogue()
by_name = {e['symbol']: e for e in catalogue7}
check('T7 real devices found in ConnectCAD\'s folder',
      'Meyer Sound_Galaxy 408' in by_name and 'Cisco_C9300' in by_name,
      repr(list(by_name)))
check('T7 and their folder is recorded',
      by_name['Meyer Sound_Galaxy 408']['folder'] == 'zConnectCAD db Created',
      repr(by_name['Meyer Sound_Galaxy 408']))
check('T7 parts from the root are still listed',
      'AudJack2FN' in by_name, repr(list(by_name)))
check('T7 but sorted below devices that name a make or model',
      [e['symbol'] for e in catalogue7][:2]
      == ['Cisco_C9300', 'Meyer Sound_Galaxy 408'],
      repr([e['symbol'] for e in catalogue7]))
check('T7 non-device symbols still excluded',
      'A Plain Symbol' not in by_name, repr(list(by_name)))

# A symbol appearing in two folders is listed once.
check('T7 no duplicates across folders',
      len(catalogue7) == len(set(e['symbol'] for e in catalogue7)),
      repr([e['symbol'] for e in catalogue7]))

# Matching still works against the folder-sourced catalogue.
check('T7 lookup finds the device, not the part',
      m.find_device_symbol('Meyer Sound', 'Galaxy 408', catalogue7)['symbol']
      == 'Meyer Sound_Galaxy 408')

R.report_and_exit()
