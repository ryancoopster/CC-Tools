"""Defects found by auditing the plug-in, and the guards that now stop them.

Each of these shipped. They are grouped by what made them survive review: a
value invented instead of read, a check that did not run, an early return that
swallowed three menu actions.
"""
import os
from harness import Doc, Obj, Results, load, dev, equip, sock

R = Results()
check = R.check
m, vs = load(Doc([[dev('x')]]))

# ── T1: the database's LOOP tokens are not socket types ──────────────────
# Socket.type takes IN/OUT/IO. The shipped database also uses LOOP (84 rows)
# and IOloop (6) to mean "loops through", and writing those verbatim gave 88
# shipped devices a type ConnectCAD does not recognise.
for token, want in (('IN', 'IN'), ('OUT', 'OUT'), ('IO', 'IO'),
                    ('LOOP', 'IO'), ('IOloop', 'IO'), ('ioLOOP', 'IO'),
                    ('', 'IO'), ('nonsense', 'IO')):
    check('T1 %-8r -> %s' % (token, want), m.db_socket_type(token) == want,
          repr(m.db_socket_type(token)))

row = [''] * 20
row[14], row[15], row[16], row[17], row[18], row[19] = \
    'RJ45', '2', 'L', 'NET ', 'LAN', 'LOOP'
specs = m.db_socket_specs({'rows': [row]})
check('T1 a LOOP row builds IO sockets',
      all(s[2] == 'IO' for s in specs) and len(specs) == 2, repr(specs))

paths = m.device_db_paths()
if paths:
    m._device_db_cache.clear()
    real = m.load_device_db()
    types = {s[2] for e in real.values() for s in m.db_socket_specs(e)}
    check('T1 the whole shipped database yields only legal types',
          types <= {'IN', 'OUT', 'IO'}, repr(sorted(types)))
else:
    check('T1 skipped, no Vectorworks here', True)

# ── T2: signal categories are not signals ────────────────────────────────
known = m.known_signals()
if known:
    for heading in ('VIDEO', 'AUDIO', 'CONTROL', 'POWER', 'NETWORK',
                    'OPTICAL', 'RADIO', 'LIGHTING'):
        check('T2 %r is a heading, not a signal' % heading, heading not in known)
    for real_signal in ('LINE', 'LAN', 'AES', 'MILAN PRI'):
        check('T2 %r is still accepted' % real_signal, real_signal in known)
    bad = {'devices': [], 'circuits': [{'from': {}, 'to': {}, 'signal': 'Video'}]}
    check('T2 a job carrying a heading is now reported',
          m.unknown_signals(bad) == {'Video'}, repr(m.unknown_signals(bad)))
else:
    check('T2 skipped, no Vectorworks here', True)

# ── T3: an illegal circuit_type cannot reach the drawing ─────────────────
# preferences.json is hand-editable, and an earlier build of this plug-in
# offered two CircuitType values that do not exist.
import json, tempfile
m.BASE_FOLDER = tempfile.mkdtemp()
for value, expect in (('rounded', 'rounded'), ('polyline', 'polyline'),
                      ('chamfer', 'chamfer'), ('', ''),
                      ('direct', ''), ('orthogonal', ''), ('arrow', ''),
                      ('ROUNDED', '')):
    with open(m.prefs_path(), 'w', encoding='utf-8') as f:
        json.dump({'circuit_type': value}, f)
    got = m.load_prefs()['circuit_type']
    check('T3 %-11r -> %r' % (value, expect), got == expect, repr(got))
check('T3 arrow is rejected even though ConnectCAD has it',
      'arrow' not in m.CIRCUIT_TYPES,
      'it is a different object, not a corner style')

# ── T4: Spell Check actions that need no suspects must still run ─────────
# find_suspects is deliberately conservative, so an empty list is the NORMAL
# state -- and exactly the state someone doing bulk vocabulary work is in.
import inspect
body = inspect.getsource(m.tool_spellcheck)
early = body.index('if not suspects')
check('T4 the early return is gated on the action',
      "settings['action'] in (ACTION_SPELL_REVIEW" in body[early:early + 260],
      body[early:early + 260])
for action in ('ACTION_SPELL_LIST', 'ACTION_SPELL_VOCAB', 'ACTION_SPELL_APPLY'):
    check('T4 %s is not gated behind suspects' % action,
          body.index(action) > early or action not in body[:early],
          'these work from the word list or the CSV, not from suspects')
for action in ('ACTION_SPELL_REVIEW', 'ACTION_SPELL_EXPORT', 'ACTION_SPELL_ALL'):
    check('T4 %s still needs suspects' % action,
          action in body[early:early + 260], body[early:early + 260])

# ── T5: Find and Replace has the socket-collision guard ──────────────────
replace = inspect.getsource(m.tool_find_replace)
check('T5 collisions are checked', 'find_socket_collisions' in replace)
check('T5 before anything is written',
      replace.index('find_socket_collisions') < replace.index('apply_edits('),
      'checking afterwards would be checking the damage')

DOC = Doc([[
    Obj('Device', {'name': 'AMP', 'tag': 'AMP'},
        children=[sock('LAN_IN A'), sock('LAN_IN B')]),
]])
mod, _vs = load(DOC)
hs = mod.walk_document()
socks = [h for h in hs if mod.classify(h) == 'socket']
eds = [mod.make_edit(socks[1], 'socket', 'name', 'LAN_IN B', 'LAN_IN A', True)]
_w, par = mod.walk_document(with_parents=True)
check('T5 collapsing two socket names onto one is detected',
      mod.find_socket_collisions(eds, par) != {},
      repr(mod.find_socket_collisions(eds, par)))

# ── T6: no invented signal or connector on a generated socket ────────────
probe = inspect.getsource(m.probe_make_device)
check('T6 no invented LAN default', "'signal', spec_signal or 'LAN'" not in probe)
check('T6 no invented EC-6A default',
      "'connector', spec_connector or 'EC-6A'" not in probe)
check('T6 a blank stays blank', 'if spec_signal:' in probe
      and 'if spec_connector:' in probe, probe[:0])

# ── T7: a fallback rename is announced by every tool, not one ────────────
note = inspect.getsource(m.fallback_rename_note)
check('T7 the note exists and is shared', 'apply_edits.fallback_renames' in note)
m.apply_edits.fallback_renames = 0
check('T7 silent when the path was available', m.fallback_rename_note() == '')
m.apply_edits.fallback_renames = 3
said = m.fallback_rename_note()
check('T7 says how many and what it means',
      '3' in said and 'links were NOT' in said.replace('rack equipment links',
                                                        'links'),
      repr(said[:120]))
m.apply_edits.fallback_renames = 0

R.report_and_exit()
