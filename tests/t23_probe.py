"""Creation-probe tests.

The probe exists to find out whether generating schematics is possible at all,
so its own reporting has to be trustworthy: a step that silently fails must
read as a failure, never as success.
"""
from harness import Doc, Obj, Results, load, dev

R = Results()
check = R.check


def wire_mock(vs, mod, *, device_ok=True, group_ok=True, symbol_ok=True,
              connect_ok=True, circuits=()):
    """Stub the Vectorworks side of creation with selectable failures."""
    made = {'devices': [], 'sockets': []}

    deleted = []
    vs.Rect = lambda *a: None
    vs.LNewObj = lambda: Obj('Rect', {})
    vs.DelObject = lambda h: deleted.append(h)
    # Two frames: a device reports document bounds, profile-group contents
    # report device-local ones. Conflating them is the bug under test.
    boxes = {}
    made['boxes'] = boxes
    vs.GetBBox = lambda h: boxes.get(id(h), (0.0, 1.0, 2.0, 0.0))
    made['deleted'] = deleted
    moves = []
    made['moves'] = moves
    vs.HMove = lambda h, dx, dy: moves.append((dx, dy))
    vs.DSelectAll = lambda: None
    calls_absolute = []
    attrs = []
    made['absolute'] = calls_absolute
    made['attrs'] = attrs
    vs.Absolute = lambda: calls_absolute.append(True)
    vs.PushAttrs = lambda: attrs.append('push')
    vs.PopAttrs = lambda: attrs.append('pop')
    vs.ActLayer = lambda: 'LAYER0'
    vs.GetLName = lambda l: 'Schematic'
    vs.GetLScale = lambda l: 2.0
    vs.SetSelect = lambda h: None
    def remember(name):
        vs.wanted['name'] = name
        return None
    vs.GetObject = remember
    vs.BuildResourceList = lambda t, f, sub: (1, 1 if symbol_ok else 0)
    vs.wanted = {'name': None}
    _orig_build = vs.BuildResourceList
    def build(t, f, sub):
        return _orig_build(t, f, sub)
    vs.BuildResourceList = build
    # Return whichever symbol was asked for, so both skt_R and skt_L resolve.
    vs.GetNameFromResourceList = lambda lid, i: vs.wanted['name']
    vs.ImportResourceToCurrentFile = lambda lid, i: Obj('SymDef', {})
    vs.FInSymDef = lambda sym: Obj('Socket', {'name': '', 'tag': '', 'type': ''})
    def duplicate(proto, group):
        # A real duplicate lands INSIDE the profile group, which is what
        # measure() walks to report socket positions.
        made['sockets'].append(proto)
        if hasattr(group, 'children'):
            group.children.append(proto)
        return proto
    vs.CreateDuplicateObject = duplicate

    if device_ok:
        def make(rect):
            d = Obj('Device', {'name': '', 'tag': '', 'make': '', 'model': ''})
            made['devices'].append(d)
            return d
        vs.CC_DeviceFromShape = make
    else:
        vs.CC_DeviceFromShape = lambda rect: None

    groups = {}

    def profile_group(h):
        if not group_ok:
            return None
        if h not in groups:
            # CC_DeviceFromShape duplicates the source shape into the group;
            # that shape is the device body and is what body_bounds measures.
            groups[h] = Obj('Group', {}, children=[Obj('Rect', {})])
        return groups[h]
    vs.GetCustomObjectProfileGroup = profile_group

    calls = []
    if connect_ok:
        vs.DoMenuTextByName = lambda name, n: calls.append(name)
    else:
        def boom(name, n):
            raise RuntimeError('no such menu command')
        vs.DoMenuTextByName = boom

    mod.walk_document = lambda with_parents=False: list(circuits)
    mod.circuit_endpoints = lambda c, ids=None: (
        {'device': 'CCTOOLS PROBE A', 'socket': 'OUT 1'},
        {'device': 'CCTOOLS PROBE B', 'socket': 'IN 1'})
    return made, calls


def run(**kw):
    m, vs = load(Doc([[dev('x')]]))
    made, calls = wire_mock(vs, m, **kw)
    vs.AlertQuestion = lambda *a: 1              # user confirms
    status, summary = m.tool_creation_probe()
    return m, vs, made, calls, status, summary


# ── T1: the happy path reports success ──────────────────────────────────────
m, vs, made, calls, status, summary = run(circuits=[Obj('Circuit', {})])
check('T1 two devices created', len(made['devices']) == 2, repr(made['devices']))
check('T1 three sockets duplicated into each device',
      len(made['sockets']) == 6, repr([o.fields.get('name') for o in made['sockets']]))
check('T1 ConnectSelected invoked', calls == ['ConnectSelected'], repr(calls))
check('T1 verdict is possible', 'is possible' in (summary or ''), repr(summary))

# ── T2: a failure anywhere must NOT read as success ─────────────────────────
_m, _vs, _made, _calls, _s, summary = run(device_ok=False)
check('T2 no device -> NOT possible', 'NOT possible' in (summary or ''),
      repr(summary))

_m, _vs, _made, _calls, _s, summary = run(group_ok=False,
                                          circuits=[Obj('Circuit', {})])
check('T2 no profile group -> sockets failed, NOT possible',
      'NOT possible' in (summary or '') and 'sockets' in (summary or ''),
      repr(summary))

_m, _vs, _made, _calls, _s, summary = run(connect_ok=False,
                                          circuits=[Obj('Circuit', {})])
check('T2 ConnectSelected failure -> NOT possible',
      'NOT possible' in (summary or ''), repr(summary))

# ── T3: wiring is judged by the association, not by the command running ─────
# ConnectSelected returning cleanly proves nothing; only a readable circuit does.
m3, vs3 = load(Doc([[dev('x')]]))
made3, calls3 = wire_mock(vs3, m3, circuits=[])      # command runs, no circuit
vs3.AlertQuestion = lambda *a: 1
_status, summary3 = m3.tool_creation_probe()
check('T3 command running is not proof of wiring',
      calls3 == ['ConnectSelected'] and 'NOT possible' in (summary3 or ''),
      repr(summary3))

# ── T4: declining writes nothing ────────────────────────────────────────────
m4, vs4 = load(Doc([[dev('x')]]))
made4, _c = wire_mock(vs4, m4)
vs4.AlertQuestion = lambda *a: 0                     # user cancels
status4, summary4 = m4.tool_creation_probe()
check('T4 cancelling creates nothing', made4['devices'] == [], repr(made4))
check('T4 and reports cancelled', status4 == 'cancelled', repr(status4))

# ── T5: it warns that it writes ─────────────────────────────────────────────
import os
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'cc_tools.py'), encoding='utf-8').read()
check('T5 dialog says it writes', 'WRITES two throwaway devices' in src)
check('T5 dialog says scratch file', 'scratch file' in src)
check('T5 launcher entry is labelled as writing',
      "Creation Probe  (writes - scratch file only)" in src)


# ── T6: the source rectangle is cleaned up ──────────────────────────────────
# CC_DeviceFromShape duplicates the shape into the profile group and leaves the
# original behind, so without an explicit delete every generated device sits on
# top of an orphan rectangle.
m6, vs6, made6, _c, _s, _sum = run(circuits=[Obj('Circuit', {})])
check('T6 source rectangle deleted for each device',
      len(made6['deleted']) == 2, repr(made6['deleted']))

# ── T7: a left socket goes to the LEFT edge ─────────────────────────────────
check('T7 sockets placed on both sides',
      len(made6['moves']) == 6, repr(made6['moves']))

# ── T8: sockets get a signal and connector, not '???' ───────────────────────
sockets = [o for o in made6['sockets']]
check('T8 signal set on the socket',
      all(o.fields.get('signal') for o in sockets), repr([o.fields for o in sockets]))
check('T8 connector set on the socket',
      all(o.fields.get('connector') for o in sockets),
      repr([o.fields for o in sockets]))

# ── T9: geometry is measured, so placement can be calibrated ────────────────
import os
log = None
for name in sorted(os.listdir(m6.BASE_FOLDER), reverse=True):
    if name.startswith('creation_probe'):
        log = open(os.path.join(m6.BASE_FOLDER, name), encoding='utf-8').read()
        break
check('T9 a log was written', log is not None)
check('T9 device bounds reported', 'device (doc)' in (log or ''), (log or '')[:200])
check('T9 body bounds reported in the local frame',
      'body (local)' in (log or ''), (log or '')[:400])
check('T9 each socket drop reported in units AND paper inches',
      'on paper' in (log or ''), (log or '')[:400])
check('T9 the layer scale is reported',
      'layer scale' in (log or ''), (log or '')[:400])
check('T9 the unit conversion is reported',
      'unit(s) per inch' in (log or ''), (log or '')[:400])


# ── T10: sockets are placed from MEASURED bounds, not requested size ────────
# ConnectCAD sizes the device itself: a 2.0 x 1.0 request came back 3.0 x 1.4
# in a real document, so anything derived from the requested width misses.
m10, vs10 = load(Doc([[dev('x')]]))
moved = []
vs10.HMove = lambda h, dx, dy: moved.append((round(dx, 4), round(dy, 4)))

# GetBBox reports top before bottom; bounds() must normalise that.
vs10.GetBBox = lambda h: (-0.195, 0.142, 0.062, -0.063)
socket = Obj('Socket', {})
device_box = (-1.5, 0.0, 1.5, 1.4)          # left, bottom, right, top

check('T10 bounds normalises top/bottom order',
      m10.bounds(socket) == (-0.195, -0.063, 0.062, 0.142), repr(m10.bounds(socket)))

m10.place_socket(socket, device_box, 1, 0, 1.0, 1.0)
# socket centre is (-0.0665, 0.0395); target is the right edge, 0.5" below top
check('T10 right socket lands on the right edge',
      moved and abs(moved[-1][0] - (1.5 - -0.0665)) < 0.001, repr(moved))
check('T10 first socket sits half an inch below the HEADER',
      moved and abs(moved[-1][1] - (-0.5 - 0.0395)) < 0.001, repr(moved))

moved[:] = []
m10.place_socket(socket, device_box, -1, 0, 1.0, 1.0)
check('T10 left socket lands on the left edge',
      moved and abs(moved[-1][0] - (-1.5 - -0.0665)) < 0.001, repr(moved))

moved[:] = []
check('T10 missing bounds is refused, not guessed',
      m10.place_socket(socket, None, 1, 0, 1.0, 1.0) is False and moved == [])

# ── T11: the stray-rectangle warning is gone ────────────────────────────────
# It counted every rectangle in the document, so a real drawing's own
# rectangles were reported as leftovers from the probe.
import os
src_text = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'cc_tools.py'), encoding='utf-8').read()
check('T11 no document-wide loose-rectangle count',
      'loose rectangle(s) remain' not in src_text)


# ── T12: the two coordinate frames are not conflated ────────────────────────
# A socket lives in the device's profile group (device-LOCAL coordinates);
# GetBBox on the device reports DOCUMENT coordinates. Placing from the device's
# own bounds works only for a device straddling the origin, which is why one
# probe device looked right and the other landed far off to the side.
m12, vs12 = load(Doc([[dev('x')]]))
moved12 = []
vs12.HMove = lambda h, dx, dy: moved12.append((round(dx, 4), round(dy, 4)))

body = Obj('Rect', {})                       # the duplicated body shape
group = Obj('Group', {}, children=[body])
socket12 = Obj('Socket', {})
group.children.append(socket12)

# Body sits at local -1.5..1.5 x 0..1.4 regardless of where the device is.
local = {id(body): (-1.5, 1.4, 1.5, 0.0), id(socket12): (-0.195, 0.142, 0.062, -0.063)}
vs12.GetBBox = lambda h: local.get(id(h), (0.0, 0.0, 0.0, 0.0))

measured = m12.body_bounds(group)
check('T12 body measured in the local frame',
      measured == (-1.5, 0.0, 1.5, 1.4), repr(measured))
check('T12 sockets excluded from the body measurement',
      measured[2] == 1.5, repr(measured))

m12.place_socket(socket12, measured, -1, 0, 1.0, 1.0)
check('T12 left socket moves to the LOCAL left edge',
      moved12 and abs(moved12[-1][0] - (-1.5 - -0.0665)) < 0.001, repr(moved12))
check('T12 vertical measured from the header baseline',
      moved12 and abs(moved12[-1][1] - (-0.5 - 0.0395)) < 0.001, repr(moved12))

# The device's document position must not influence placement at all.
moved12[:] = []
m12.place_socket(socket12, measured, -1, 0, 1.0, 1.0)
first = moved12[-1]
local[id(body)] = (-1.5, 1.4, 1.5, 0.0)      # same body, device moved elsewhere
moved12[:] = []
m12.place_socket(socket12, m12.body_bounds(group), -1, 0, 1.0, 1.0)
check('T12 placement is independent of where the device sits',
      moved12[-1] == first, '%r vs %r' % (moved12[-1], first))

check('T12 no body -> refused, not guessed',
      m12.place_socket(socket12, None, 1, 0, 1.0, 1.0) is False)


# ── T13: the house spacing convention ───────────────────────────────────────
# First socket half an inch below the top of the block, every one after it a
# quarter inch below the last -- read off the Chautauqua and Geffen drawings.
m13, vs13 = load(Doc([[dev('x')]]))
check('T13 first drop is half an inch', m13.SOCKET_FIRST_DROP_IN == 0.5)
check('T13 pitch is a quarter inch', m13.SOCKET_PITCH_IN == 0.25)
check('T13 drop for the first socket', m13.socket_drop(0, 1.0) == 0.5)
check('T13 drop for the second', m13.socket_drop(1, 1.0) == 0.75)
check('T13 drop for the fifth', m13.socket_drop(4, 1.0) == 1.5)
check('T13 scales with document units',
      m13.socket_drop(1, 25.4) == 0.75 * 25.4, repr(m13.socket_drop(1, 25.4)))

# Spacing must not depend on how tall the block is: a taller device keeps the
# same pitch rather than spreading its sockets out.
moved13 = []
vs13.HMove = lambda h, dx, dy: moved13.append(round(dy, 4))
vs13.GetBBox = lambda h: (-1.5, 1.4, 1.5, -1.0)
sk = Obj('Socket', {})
short_body = (-1.5, 0.0, 1.5, 1.4)
tall_body = (-1.5, -6.0, 1.5, 1.4)
for body in (short_body, tall_body):
    moved13[:] = []
    for i in range(3):
        m13.place_socket(sk, body, 1, i, 1.0, 1.0)
    gaps = [round(moved13[i] - moved13[i + 1], 4) for i in range(len(moved13) - 1)]
    check('T13 pitch holds on a {} block'.format(
        'short' if body is short_body else 'tall'),
        gaps == [0.25, 0.25], repr(gaps))

# Sockets on opposite sides each start their own stack.
m14, vs14 = load(Doc([[dev('x')]]))
made14, _c = wire_mock(vs14, m14, circuits=[Obj('Circuit', {})])
vs14.AlertQuestion = lambda *a: 1
m14.tool_creation_probe()
drops = [dy for dx, dy in made14['moves']]
check('T14 three sockets placed per device', len(drops) == 6, repr(drops))
check('T14 each side restarts the stack',
      drops[:3] == drops[3:], repr(drops))


# ── T15: the convention is PAPER inches, so layer scale applies ─────────────
# Design-layer geometry is stored at world size; the layer scale maps it to the
# printed sheet. A schematic at 1:2 needs twice the drawing distance to print
# the same gap, so ignoring scale is wrong by exactly the scale factor.
m15, vs15 = load(Doc([[dev('x')]]))
check('T15 1:1 leaves the paper figure alone',
      m15.socket_drop(0, 1.0, 1.0) == 0.5)
check('T15 1:2 doubles the drawing distance',
      m15.socket_drop(0, 1.0, 2.0) == 1.0, repr(m15.socket_drop(0, 1.0, 2.0)))
check('T15 pitch scales too',
      m15.socket_drop(1, 1.0, 2.0) - m15.socket_drop(0, 1.0, 2.0) == 0.5)
check('T15 1:48 scales as far',
      m15.socket_drop(0, 1.0, 48.0) == 24.0, repr(m15.socket_drop(0, 1.0, 48.0)))
check('T15 units and scale compose',
      m15.socket_drop(0, 25.4, 2.0) == 0.5 * 25.4 * 2.0)

# An unreadable scale must draw at world size, not guess a factor.
vs15.GetLScale = lambda layer: 0
value, note = m15.layer_scale()
check('T15 a nonsense scale falls back to 1:1', value == 1.0, repr((value, note)))
def boom(layer):
    raise RuntimeError('no layer')
vs15.GetLScale = boom
value, note = m15.layer_scale()
check('T15 a failing scale falls back to 1:1 and says so',
      value == 1.0 and 'GetLScale failed' in note, repr(note))

vs15.GetLScale = lambda layer: 2.0
value, note = m15.layer_scale()
check('T15 a real scale is reported as a ratio', value == 2.0 and note == '1:2',
      repr(note))


# ── T16: objects land on the ACTIVE layer, sized to ITS scale ───────────────
m16, vs16 = load(Doc([[dev('x')]]))
made16, _c = wire_mock(vs16, m16, circuits=[Obj('Circuit', {})])
vs16.AlertQuestion = lambda *a: 1
m16.tool_creation_probe()

import os
log16 = None
for name in sorted(os.listdir(m16.BASE_FOLDER), reverse=True):
    if name.startswith('creation_probe'):
        log16 = open(os.path.join(m16.BASE_FOLDER, name), encoding='utf-8').read()
        break

check('T16 names the active layer it is drawing on',
      'Inserting on the ACTIVE layer: Schematic' in (log16 or ''),
      (log16 or '')[:300])
check('T16 reports that layer\'s scale', '1:2' in (log16 or ''), (log16 or '')[:300])

# Relative coordinate mode persists across a session; left set by anything
# earlier, every Rect would land somewhere unintended.
check('T16 forces absolute coordinates', made16['absolute'], repr(made16['absolute']))

# The active class and attributes belong to the user.
check('T16 borrows and returns the drawing attributes',
      made16['attrs'] == ['push', 'pop'], repr(made16['attrs']))

# Spacing must come from the active layer's scale, not a default.
drops16 = [dy for dx, dy in made16['moves']]
gaps16 = [round(drops16[i] - drops16[i + 1], 4) for i in range(2)]
check('T16 pitch doubled by the 1:2 layer scale',
      gaps16 == [0.5, 0.5], repr(gaps16))


# ── T17: units are not guessed out of GetUnits ──────────────────────────────
# GetUnits returns several values; picking the plausible-looking one returned
# 25.0 on an inch drawing and multiplied every socket drop by 25.
m17, vs17 = load(Doc([[dev('x')]]))
vs17.GetUnits = lambda: (2, 25.0, 1, 0)
upi, note = m17.units_per_inch()
check('T17 a stray 25.0 in GetUnits is ignored', upi == 1.0, repr((upi, note)))
check('T17 and the assumption is stated', 'inch' in note, repr(note))

# The raw values are still reported, so the right field can be identified.
raw = m17.raw_units_report()
check('T17 raw GetUnits values are logged', '25.0' in raw and '[1]' in raw, repr(raw))

vs17.GetUnits = lambda: (_ for _ in ()).throw(RuntimeError('nope'))
check('T17 a failing GetUnits is reported, not fatal',
      'failed' in m17.raw_units_report(), repr(m17.raw_units_report()))

# With units at 1.0 and a 1:1 layer, the drops are the stated inches.
check('T17 first drop is half an inch of drawing',
      m17.socket_drop(0, 1.0, 1.0) == 0.5)
check('T17 third socket sits one inch down',
      m17.socket_drop(2, 1.0, 1.0) == 1.0)


# ── T18: sockets hang from the HEADER, not the top of the block ─────────────
# CC_DeviceFromShape adds a header above the rectangle it is given: a 1.0-tall
# request came back as body -1.000..0.400, so local y = 0 is the header's
# bottom edge. Measuring from the block top puts the whole stack a header's
# height too high -- a constant error that reads as a bad offset.
m18, vs18 = load(Doc([[dev('x')]]))
body18 = (-1.5, -1.0, 1.5, 0.4)          # local: body -1.0..0, header 0..0.4
check('T18 sockets hang from local y = 0', m18.header_baseline(body18) == 0.0)

moved18 = []
vs18.HMove = lambda h, dx, dy: moved18.append(round(dy, 4))
vs18.GetBBox = lambda h: (-0.13, 0.1, 0.13, -0.1)     # socket centred on origin
sk18 = Obj('Socket', {})
for i in range(3):
    m18.place_socket(sk18, body18, 1, i, 1.0, 1.0)
check('T18 first socket half an inch below the header',
      abs(moved18[0] - -0.5) < 0.001, repr(moved18))
check('T18 second a quarter inch below that',
      abs(moved18[1] - -0.75) < 0.001, repr(moved18))
check('T18 third another quarter down',
      abs(moved18[2] - -1.0) < 0.001, repr(moved18))
check('T18 none sit inside the header',
      all(v < 0 for v in moved18), repr(moved18))

# A taller header must not move the stack: the baseline is the origin.
tall_header = (-1.5, -1.0, 1.5, 2.0)
moved18[:] = []
m18.place_socket(sk18, tall_header, 1, 0, 1.0, 1.0)
check('T18 header height does not shift the stack',
      abs(moved18[0] - -0.5) < 0.001, repr(moved18))


# ── T19: the profile group is inventoried, not assumed ──────────────────────
# The header and the body are both drawn by ConnectCAD; only one of them is the
# rectangle handed in, so which is which must be read from the drawing.
m19, vs19 = load(Doc([[dev('x')]]))
body19 = Obj('Rect', {})
skt19 = Obj('Socket', {'name': 'OUT 1', 'tag': 'OUT 1', 'type': 'OUT'})
group19 = Obj('Group', {}, children=[body19, skt19])
vs19.GetBBox = lambda h: (-1.5, 0.4, 1.5, -1.0)

lines19 = m19.group_inventory(group19)
check('T19 every object in the group is listed', len(lines19) == 2, repr(lines19))
check('T19 records are named', any('Socket' in l for l in lines19), repr(lines19))
check('T19 widths are reported', all('w ' in l for l in lines19), repr(lines19))
check('T19 a missing group is stated, not crashed',
      'no profile group' in m19.group_inventory(None)[0])

# ── T20: the width comparison reaches the log ───────────────────────────────
m20, vs20 = load(Doc([[dev('x')]]))
made20, _c = wire_mock(vs20, m20, circuits=[Obj('Circuit', {})])
vs20.AlertQuestion = lambda *a: 1
m20.tool_creation_probe()

import os
log20 = None
for name in sorted(os.listdir(m20.BASE_FOLDER), reverse=True):
    if name.startswith('creation_probe'):
        log20 = open(os.path.join(m20.BASE_FOLDER, name), encoding='utf-8').read()
        break
check('T20 header vs body widths compared', 'difference' in (log20 or ''),
      (log20 or '')[:400])
check('T20 group contents listed', 'in group:' in (log20 or ''), (log20 or '')[:400])
check('T20 the long-name experiment is labelled in the log',
      'LONG name' in (log20 or '') and 'SHORT name' in (log20 or ''),
      (log20 or '')[:400])

R.report_and_exit()
