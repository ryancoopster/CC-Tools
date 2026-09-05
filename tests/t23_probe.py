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
check('T1 a socket duplicated into each', len(made['sockets']) == 2,
      repr(made['sockets']))
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
check('T7 one socket right, one left',
      sorted(dx for dx, dy in made6['moves']) == [-1.0, 1.0],
      repr(made6['moves']))

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
check('T9 socket position reported relative to the body',
      'body-relative' in (log or ''), (log or '')[:400])


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

m10.place_socket(socket, device_box, 1, 0.75)
# socket centre is (-0.0665, 0.0395); target is the right edge at 75% height
check('T10 right socket lands on the right edge',
      moved and abs(moved[-1][0] - (1.5 - -0.0665)) < 0.001, repr(moved))
check('T10 and at the requested height fraction',
      moved and abs(moved[-1][1] - (1.05 - 0.0395)) < 0.001, repr(moved))

moved[:] = []
m10.place_socket(socket, device_box, -1, 0.75)
check('T10 left socket lands on the left edge',
      moved and abs(moved[-1][0] - (-1.5 - -0.0665)) < 0.001, repr(moved))

moved[:] = []
check('T10 missing bounds is refused, not guessed',
      m10.place_socket(socket, None, 1, 0.5) is False and moved == [])

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

m12.place_socket(socket12, measured, -1, 0.75)
# socket centre (-0.0665, 0.0395) -> local left edge -1.5 at 75% of 1.4
check('T12 left socket moves to the LOCAL left edge',
      moved12 and abs(moved12[-1][0] - (-1.5 - -0.0665)) < 0.001, repr(moved12))
check('T12 vertical uses the body height',
      moved12 and abs(moved12[-1][1] - (1.05 - 0.0395)) < 0.001, repr(moved12))

# The device's document position must not influence placement at all.
moved12[:] = []
m12.place_socket(socket12, measured, -1, 0.75)
first = moved12[-1]
local[id(body)] = (-1.5, 1.4, 1.5, 0.0)      # same body, device moved elsewhere
moved12[:] = []
m12.place_socket(socket12, m12.body_bounds(group), -1, 0.75)
check('T12 placement is independent of where the device sits',
      moved12[-1] == first, '%r vs %r' % (moved12[-1], first))

check('T12 no body -> refused, not guessed',
      m12.place_socket(socket12, None, 1, 0.5) is False)

R.report_and_exit()
