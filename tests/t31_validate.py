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

R.report_and_exit()
