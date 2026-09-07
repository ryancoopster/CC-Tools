"""Checks that would have caught the first real job.

It drew 50 devices and wired 22 of 46 circuits. Nothing in the tool objected,
because nothing looked at the geometry before drawing it.
"""
import json
from harness import Doc, Results, load, dev

R = Results()
check = R.check
m, vs = load(Doc([[dev('x')]]))
G = 0.25


def spk(ident, column, align_socket):
    return {'id': ident, 'name': ident.upper(), 'make': 'Meyer Sound',
            'model': 'TIGRA-L', 'column': column, 'section': 'Net',
            'align_to': {'device': 'sw', 'socket': align_socket,
                         'my_socket': 'LAN_IN 1'},
            'sockets': [{'name': 'LAN_IN 1', 'type': 'IN', 'signal': 'LAN',
                         'side': 'L'}]}


SWITCH = {'id': 'sw', 'name': 'SW', 'make': 'Luminex', 'model': '30i 10G POE',
          'column': 0, 'section': 'Net',
          'sockets': [{'name': 'LAN %d' % n, 'type': 'IO', 'signal': 'LAN',
                       'side': 'R'} for n in range(1, 9)]}

# ── T1: the exact shape that failed — a fan-out sharing one column ────────
job = {'devices': [SWITCH] + [spk('s%d' % n, 1, 'LAN %d' % n)
                              for n in range(1, 6)], 'circuits': []}
pos, _n = m.resolve_job_positions(job, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
clashes = m.find_overlaps(job, pos, 1.0, 1.0, G)
check('T1 a same-column fan-out is caught', len(clashes) > 0,
      'this is what drew 50 devices and wired almost nothing')
check('T1 the overlap is half an inch',
      abs(max(c[2] for c in clashes) - 0.5) < 1e-9,
      repr([c[2] for c in clashes[:3]]))
check('T1 every consecutive pair clashes', len(clashes) >= 4, repr(len(clashes)))

# ── T2: a column each is clean ───────────────────────────────────────────
job = {'devices': [SWITCH] + [spk('s%d' % n, n, 'LAN %d' % n)
                              for n in range(1, 6)], 'circuits': []}
pos, _n = m.resolve_job_positions(job, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T2 a staircase does not overlap',
      m.find_overlaps(job, pos, 1.0, 1.0, G) == [],
      repr(m.find_overlaps(job, pos, 1.0, 1.0, G)))

# ── T3: devices in different sections never clash ────────────────────────
a = dict(spk('a', 0, 'LAN 1'), section='One')
b = dict(spk('b', 0, 'LAN 1'), section='Two')
a.pop('align_to'); b.pop('align_to')
job = {'devices': [a, b], 'circuits': []}
pos, _n = m.resolve_job_positions(job, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T3 separate sections are not overlaps',
      m.find_overlaps(job, pos, 1.0, 1.0, G) == [])

# ── T4: signals are checked against ConnectCAD's vocabulary ──────────────
known = m.known_signals()
if known:
    check('T4 the shipped vocabulary loads', len(known) >= 79, '%d' % len(known))
    check('T4 a standard signal is known', 'LINE' in known and 'LAN' in known)
    bad = {'devices': [], 'circuits': [
        {'from': {'device': 'a', 'socket': 'x'},
         'to': {'device': 'b', 'socket': 'y'}, 'signal': 'NOT A SIGNAL'}]}
    check('T4 an invented signal is reported',
          m.unknown_signals(bad) == {'NOT A SIGNAL'},
          repr(m.unknown_signals(bad)))
    ok = {'devices': [], 'circuits': [
        {'from': {}, 'to': {}, 'signal': 'LINE'}]}
    check('T4 a real signal is not reported', m.unknown_signals(ok) == set())
    # The user's own custom signals live in the USER copy, which uses bare CR
    # line endings. Reading only CRLF made them look undefined.
    check('T4 custom signals from the user library are found',
          'MILAN PRI' in known,
          'the user copy uses CR endings; both must be normalised')
else:
    check('T4 skipped, no Vectorworks here', True)

# ── T5: the probe's identity no longer leaks into built devices ──────────
import inspect
body = inspect.getsource(m.probe_make_device)
# Assert on the code, not the prose: the comment above it explains what the
# hard-coded values used to be, and naming them there is the point.
code = '\n'.join(l for l in body.split('\n') if not l.strip().startswith('#'))
check('T5 make and model come from the caller, not hard-coded',
      "'CC Tools'" not in code and "'Probe'" not in code
      and "('make', make)" in code, code[:0])
check('T5 they are parameters', 'make=' in inspect.signature(m.probe_make_device)
      .parameters.__str__() or 'make' in inspect.signature(m.probe_make_device).parameters)

build = inspect.getsource(m.build_device)
check('T5 description falls back to Make_Model',
      "'{}_{}'.format(make, model)" in build, build[:0])
check('T5 physical properties are applied',
      'apply_physical_properties' in build)

# ── T6: physical properties, and saying so when there are none ───────────
# The first run wrote no dimensions and said nothing, so a job that found no
# physical data looked exactly like one that applied it.
from mockvs import Obj

m._golden_cache.clear()
m._golden_cache.update(m.parse_golden_devices("""
## Known | Device

- Width: 19 in
- Height: 1.75 in
- Weight: 7.6 kg
- Power: 250 W
- Rack mounted: yes
- Rack U: 1

| Socket | Type |
|---|---|
| A | IN |
"""))
phys, source = m.device_physical('Known', 'Device')
check('T6 curated properties are found', source == 'curated list', source)
check('T6 inches are kept as inches', phys['width'] == 19.0, repr(phys))
check('T6 rack height read', phys['rack_u'] == 1.0, repr(phys))

d = Obj('Device', {'width': '', 'height': '', 'depth': '', 'weight': '',
                   'power': '', 'width_R': '', 'heightU': ''})
log = []
written = m.apply_physical_properties(d, phys, 1.0, log, 'curated list')
check('T6 written onto the device', set(written) >= {'width', 'height', 'weight',
                                                     'power', 'width_R', 'heightU'},
      repr(written))
check('T6 rack width from the flag', d.fields['width_R'] == 'full-rack',
      repr(d.fields))
check('T6 the source is logged', log and 'curated list' in log[0], repr(log))

# Document units: a drawing in feet must get feet, not inches.
feet = Obj('Device', {'width': '', 'height': '', 'depth': '', 'weight': '',
                      'power': '', 'width_R': '', 'heightU': ''})
m.apply_physical_properties(feet, phys, 1.0 / 12.0)
# Tolerance matches the storage format: values are written with '{:g}', which
# keeps six significant figures -- ample for a device dimension.
check('T6 lengths scale into document units',
      abs(float(feet.fields['width']) - 19.0 / 12.0) < 1e-4,
      repr(feet.fields['width']))
check('T6 weight is NOT scaled', feet.fields['weight'] == '7.6',
      repr(feet.fields['weight']))

# Nothing known: write nothing, and never a zero.
blank = Obj('Device', {'width': '', 'weight': ''})
check('T6 an empty dict writes nothing',
      m.apply_physical_properties(blank, {}, 1.0) == []
      and blank.fields['weight'] == '', repr(blank.fields))
check('T6 an unknown device reports no source',
      m.device_physical('Nobody', 'Nothing') == ({}, ''))

# The shipped database is the fallback, in millimetres.
db = m.db_physical({'rows': [[''] * 20]})
check('T6 an empty database row yields nothing', db == {}, repr(db))
row = [''] * 20
row[2], row[3], row[4], row[5], row[6] = '482.6', '44.45', '262.89', '3.84', '30'
mm = m.db_physical({'rows': [row]})
check('T6 millimetres convert to inches',
      abs(mm['width'] - 19.0) < 0.02 and abs(mm['height'] - 1.75) < 0.02,
      repr(mm))
check('T6 a 19-inch panel is recognised as racked', mm.get('racked') is True)
check('T6 rack height derived from the measured height',
      mm.get('rack_u') == 1.0, repr(mm))
check('T6 weight and power pass through unconverted',
      mm['weight'] == 3.84 and mm['power'] == 30.0, repr(mm))

row[2] = '200'          # not a rack panel
narrow = m.db_physical({'rows': [row]})
check('T6 a narrow device is not called racked',
      'racked' not in narrow and 'rack_u' not in narrow, repr(narrow))

# ── T7: columns stack, and an explicit arrangement is never overridden ───
# Verified in a live drawing: circuits offset by 0.10, 0.85 and 1.60 inches all
# wired, with ConnectCAD drawing elbows. Alignment was never required, so a
# fan-out belongs in one stacked column rather than a diagonal.
def one_socket(ident, column, row):
    return {'id': ident, 'name': ident.upper(), 'column': column, 'row': row,
            'section': 'S',
            'sockets': [{'name': 'IN 1', 'type': 'IN', 'side': 'L'}]}

job = {'devices': [
    {'id': 'src', 'name': 'SRC', 'column': 0, 'row': 0, 'section': 'S',
     'sockets': [{'name': 'OUT %d' % n, 'type': 'OUT', 'side': 'R'}
                 for n in range(1, 6)]}]
    + [one_socket('t%d' % n, 1, n) for n in range(5)], 'circuits': []}
pos, _n = m.resolve_job_positions(job, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T7 a stacked fan-out does not overlap',
      m.find_overlaps(job, pos, 1.0, 1.0, G) == [],
      repr(m.find_overlaps(job, pos, 1.0, 1.0, G)))
check('T7 the fan-out is one column',
      len({round(pos['t%d' % n][0], 4) for n in range(5)}) == 1,
      repr([pos['t%d' % n][0] for n in range(5)]))
tops = [pos['t%d' % n][1] for n in range(5)]
check('T7 stacked in row order', tops == sorted(tops, reverse=True), repr(tops))
gaps = [round(tops[i] - tops[i + 1], 4) for i in range(4)]
check('T7 spaced by height plus the gap', set(gaps) == {1.25}, repr(gaps))

wide = 1 * m.PREF_DEFAULTS['column_inches'] / 0.25 * G
check('T7 two columns wide, not nine',
      abs(pos['t0'][0] - pos['src'][0] - wide) < 1e-9,
      '%s vs %s' % (pos['t0'][0], pos['src'][0]))

# ── T8: an explicit arrangement is the job\'s, not the stacker\'s ─────────
# The chat decides the layout and shows it to the user in a preview. If the
# stacker moved those devices the preview would be a lie.
placed = {'devices': [
    dict(one_socket('a', 0, 0), x=0, y=0),
    dict(one_socket('b', 0, 1), x=0, y=-9.0),
    dict(one_socket('c', 0, 2), x=0, y=-18.0),
], 'circuits': []}
pos, _n = m.resolve_job_positions(placed, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T8 explicit y is kept exactly',
      [pos['a'][1], pos['b'][1], pos['c'][1]] == [0.0, -9.0, -18.0],
      repr([pos['a'][1], pos['b'][1], pos['c'][1]]))

# Mixed: some placed, some not. The placed ones must not move.
mixed = {'devices': [
    dict(one_socket('p', 0, 0), x=0, y=-5.0),
    one_socket('q', 1, 0), one_socket('r', 1, 1),
], 'circuits': []}
pos, _n = m.resolve_job_positions(mixed, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T8 a placed device is untouched by the stacker', pos['p'][1] == -5.0,
      repr(pos['p']))
check('T8 unplaced ones still stack', pos['q'][1] > pos['r'][1],
      repr((pos['q'], pos['r'])))

# align_to still wins over stacking, and is exempt.
pinned = {'devices': [
    {'id': 'f', 'name': 'F', 'column': 0, 'row': 0, 'section': 'S',
     'sockets': [{'name': 'OUT 1', 'type': 'OUT', 'side': 'R'},
                 {'name': 'OUT 2', 'type': 'OUT', 'side': 'R'}]},
    dict(one_socket('g', 1, 0),
         align_to={'device': 'f', 'socket': 'OUT 2', 'my_socket': 'IN 1'}),
], 'circuits': []}
pos, _n = m.resolve_job_positions(pinned, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
fy = pos['f'][1] - m.socket_drop(1, 1.0, 1.0, G)
gy_ = pos['g'][1] - m.socket_drop(0, 1.0, 1.0, G)
check('T8 align_to survives stacking', abs(fy - gy_) < 1e-9, '%s vs %s' % (fy, gy_))

# ── T9: parallel circuits from one device fan their elbows out ───────────
# ConnectCAD turns every circuit at the same distance out by default, so a
# fan-out into a stacked column draws all its vertical runs on top of one
# another. The real drawing staggers ControlPoint03X per circuit.
def circ():
    return Obj('Circuit', {'Signal': '', 'Cable': '', 'Label': '',
                           'CircuitType': '', 'ControlPoint03X': ''})

prefs = dict(m.PREF_DEFAULTS, circuit_stagger_inches=0.5)

first = circ()
m.finish_circuit(first, {'signal': 'LINE'}, prefs, 0, 1.0)
check('T9 the first circuit keeps ConnectCAD default routing',
      first.fields['ControlPoint03X'] == '', repr(first.fields))

offsets = []
for n in range(1, 4):
    c = circ()
    written = m.finish_circuit(c, {'signal': 'LINE'}, prefs, n, 1.0)
    offsets.append(float(c.fields['ControlPoint03X']))
    if n == 1:
        check('T9 a staggered elbow is reported', 'elbow' in written, repr(written))
check('T9 each later circuit turns further out',
      offsets == sorted(offsets) and len(set(offsets)) == 3, repr(offsets))
check('T9 spaced by the preference', offsets == [1.0, 1.5, 2.0], repr(offsets))

# Document units: a drawing in feet gets feet.
feet = circ()
m.finish_circuit(feet, {'signal': 'LINE'}, prefs, 1, 1.0 / 12.0)
check('T9 offsets scale into document units',
      abs(float(feet.fields['ControlPoint03X']) - 1.0 / 12.0) < 1e-4,
      repr(feet.fields['ControlPoint03X']))

off = dict(m.PREF_DEFAULTS, circuit_stagger_inches=0.0)
none = circ()
written = m.finish_circuit(none, {'signal': 'LINE'}, off, 3, 1.0)
check('T9 zero turns staggering off entirely',
      none.fields['ControlPoint03X'] == '' and 'elbow' not in written,
      repr(none.fields))

check('T9 the default is on', m.PREF_DEFAULTS['circuit_stagger_inches'] > 0)

# ── T10: devices sharing an X band can never be wired ────────────────────
# ConnectCAD groups the selection into columns by X-overlap and refuses to
# wire a single-column selection -- silently, with no error and nothing drawn.
def at(ident, x, y=0.0):
    return {'id': ident, 'name': ident.upper(), 'x': x, 'y': y, 'section': 'S',
            'sockets': [{'name': 'P', 'type': 'IO', 'side': 'R'}]}

def wire(a, b):
    return {'from': {'device': a, 'socket': 'P'},
            'to': {'device': b, 'socket': 'P'}}

same = {'devices': [at('a', 0), at('b', 0, -4)], 'circuits': [wire('a', 'b')]}
pos, _n = m.resolve_job_positions(same, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T10 same column is caught',
      len(m.find_column_clashes(same, pos, G)) == 1,
      repr(m.find_column_clashes(same, pos, G)))

apart = {'devices': [at('a', 0), at('b', 4, -4)], 'circuits': [wire('a', 'b')]}
pos, _n = m.resolve_job_positions(apart, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T10 four inches apart is fine',
      m.find_column_clashes(apart, pos, G) == [], repr(m.find_column_clashes(apart, pos, G)))

# ConnectCAD uses <=, so touching edges count as one column. Devices are 3in
# wide, so centres exactly 3in apart touch.
touch = {'devices': [at('a', 0), at('b', 3, -4)], 'circuits': [wire('a', 'b')]}
pos, _n = m.resolve_job_positions(touch, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T10 touching edges count as overlapping',
      len(m.find_column_clashes(touch, pos, G)) == 1,
      'ConnectCAD tests with <=, so exact contact is one column')

near = {'devices': [at('a', 0), at('b', 3.5, -4)], 'circuits': [wire('a', 'b')]}
pos, _n = m.resolve_job_positions(near, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T10 a real gap is not a clash', m.find_column_clashes(near, pos, G) == [])

# One report per device pair, however many circuits run between them.
many = {'devices': [at('a', 0), at('b', 0, -4)],
        'circuits': [wire('a', 'b'), wire('a', 'b'), wire('a', 'b')]}
pos, _n = m.resolve_job_positions(many, G, G, 1.0, 1.0, m.PREF_DEFAULTS)
check('T10 reported once per pair, not once per circuit',
      len(m.find_column_clashes(many, pos, G)) == 1,
      repr(m.find_column_clashes(many, pos, G)))
check('T10 a circuit to itself is ignored',
      m.find_column_clashes({'devices': [at('a', 0)],
                             'circuits': [wire('a', 'a')]},
                            {'a': (0, 0)}, G) == [])

R.report_and_exit()
