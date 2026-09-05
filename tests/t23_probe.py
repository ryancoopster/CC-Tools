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
    vs.GetBBox = lambda h: (0.0, 0.0, 2.0, 1.0)
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
            groups[h] = Obj('Group', {})
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
check('T9 device bounds reported', 'device bounds' in (log or ''), (log or '')[:200])
check('T9 socket position reported relative to the device',
      'device-relative' in (log or ''), (log or '')[:400])

R.report_and_exit()
