"""Link-invariant regression suite.

These cover the failure modes that actually bit during development: silent
unlinking, duplicate-name mis-linking, sentinel-as-key, and blank-as-key.
"""
import random
from harness import Doc, Results, load, dev, equip, pconn, panel

R = Results()
check = R.check

# ── A: stored association beats name matching on duplicate names ────────────
a, b = dev('swtch 4.01'), dev('swtch 4.01')
ea, eb = equip('swtch 4.01'), equip('swtch 4.01')
m, vs = load(Doc([[a, b], [ea, eb]]), associations={a: ea, b: eb})
edits, _u, _s = m.plan_renames([a], True, False, False, True, False)
sync, used = m.plan_link_sync(edits, {})
check('A association layer used', used)
check('A only the linked equipment follows',
      len(sync) == 1 and sync[0]['handle'] is ea,
      repr([(e['kind'], e['old'], e['new']) for e in sync]))
m.apply_edits(edits + sync)
check("A other device's equipment untouched", eb.fields['name'] == 'swtch 4.01',
      repr(eb.fields['name']))

# ── B: without the routine it falls back, and says so ───────────────────────
a2, b2 = dev('swtch 4.01'), dev('swtch 4.01')
ea2, eb2 = equip('swtch 4.01'), equip('swtch 4.01')
m2, _v = load(Doc([[a2, b2], [ea2, eb2]]))
e2, _u, _s = m2.plan_renames([a2], True, False, False, True, False)
s2, used2 = m2.plan_link_sync(e2, {})
check('B fallback flagged as a guess', not used2)
check('B fallback renames both (known wrong, reported)', len(s2) == 2)

# ── C: a device with no stored association still finds its name-mate ────────
# ConnectCAD re-links by name when no association survives, so this must too --
# but only over equipment no other device already claims.
d3, other = dev('amp 1'), dev('cam 9')
mine, theirs = equip('amp 1'), equip('cam 9')
m3, _v = load(Doc([[d3, other], [mine, theirs]]), associations={other: theirs})
e3, _u, _s = m3.plan_renames([d3], True, False, False, True, False)
s3, _ua = m3.plan_link_sync(e3, {})
m3.apply_edits(e3 + s3)
check('C unassociated device still drags its name-mate',
      mine.fields['name'] == 'AMP 1', repr(mine.fields['name']))
check('C but never steals a claimed equipment item',
      theirs.fields['name'] == 'cam 9', repr(theirs.fields['name']))

# ── D: sentinels and blanks are never link keys ─────────────────────────────
u1 = dev('<DEVICE>', 'SPK 1')
ue, up = equip('<DEVICE>'), pconn('<DEVICE>')
m4, _v = load(Doc([[u1], [ue, up]]), associations={})
_d, parents = m4.walk_document(with_parents=True)
rows, _u, _s, _sk = m4.find_mismatches([u1], True, False, include_empty=True)
e4, _sb = m4.plan_choices([(rows[0], 'tag')])
s4, _ua = m4.plan_link_sync(e4, parents)
check('D placeholder drags no partner', s4 == [],
      repr([(e['kind'], e['old'], e['new']) for e in s4]))
m4.apply_edits(e4 + s4)
check('D unrelated equipment untouched', ue.fields['name'] == '<DEVICE>')
check('D unrelated connector untouched', up.fields['ConnectedDev'] == '<DEVICE>')
check('D intended device renamed', u1.fields['name'] == 'SPK 1')

# ── E: panel and connector follow a device rename by name ───────────────────
d5 = dev('grid patch')
p5, c5 = panel('grid patch'), pconn('grid patch')
m5, _v = load(Doc([[d5], [p5, c5]]), associations={})
e5, _u, _s = m5.plan_renames([d5], True, False, False, True, False)
s5, _ua = m5.plan_link_sync(e5, {})
m5.apply_edits(e5 + s5)
check('E panel layout followed', p5.fields['DeviceName'] == 'GRID PATCH',
      repr(p5.fields['DeviceName']))
check('E panel connector followed', c5.fields['ConnectedDev'] == 'GRID PATCH',
      repr(c5.fields['ConnectedDev']))

# ── F: a device rename beats an independent edit on its own equipment ───────
# ConnectCAD severs the association when the two names diverge, so letting the
# independent edit stand would quietly unlink the pair.
d6, e6 = dev('amp 1'), equip('spk 9')
m6, _v = load(Doc([[d6], [e6]]), associations={d6: e6})
ed6, _u, _s = m6.plan_renames([d6, e6], True, True, False, True, False)
s6, _ua = m6.plan_link_sync(ed6, {})
m6.apply_edits(ed6 + s6)
check('F associated pair ends up in sync',
      d6.fields['name'] == e6.fields['name'] == 'AMP 1',
      '%r %r' % (d6.fields['name'], e6.fields['name']))

# ── G: duplicates are reported, never blocking ──────────────────────────────
g1, g2 = dev('cam 1'), dev('CAM 1')
m7, _v = load(Doc([[g1, g2]]))
e7, _u, _s = m7.plan_renames([g1, g2], True, False, False, True, False)
dupes = m7.find_duplicate_names(e7)
check('G newly created duplicate reported', len(dupes) == 1, repr(dupes))
check('G and marked as created by this run',
      all(v['created_here'] for v in dupes.values()), repr(dupes))
m7.apply_edits(e7)
check('G run was NOT blocked', g1.fields['name'] == g2.fields['name'] == 'CAM 1')

many = [dev('<DEVICE>', '') for _ in range(101)]
m8, _v = load(Doc([many]))
e8, _u, _s = m8.plan_renames(many, True, False, False, True, False)
check('G 101 unnamed devices are not duplicates',
      m8.find_duplicate_names(e8) == {}, repr(m8.find_duplicate_names(e8)))

# ── H: preview writes nothing, and says so ──────────────────────────────────
d9, e9 = dev('spk 4.05'), equip('spk 4.05')
m9, vs9 = load(Doc([[d9], [e9]]), associations={d9: e9})
m9.ask_which_tools = lambda: [m9.TOOL_NORMALISE]
m9.ask_normalise_options = lambda: {
    'scope': m9.SCOPE_DOCUMENT, 'upper': True, 'trim': True, 'devices': True,
    'equipment': False, 'sockets': False, 'sync': True, 'preview': True}
m9.run_cc_tools()
check('H preview issued zero writes', vs9.writes == [], repr(vs9.writes[:3]))
check('H preview says so loudly',
      any('PREVIEW ONLY - NOTHING WAS CHANGED' in a for a in vs9.alerts),
      repr(vs9.alerts))

# ── I: dialog defaults are what the README claims ───────────────────────────
m10, _v = load(Doc([[dev('a')]]))
norm, match, spell = (m10.ask_normalise_options(), m10.ask_match_options(),
                      m10.ask_spell_options())
picked = m10.ask_which_tools()
check('I normalise scope = selection', norm['scope'] == m10.SCOPE_SELECTION)
check('I normalise preview off', norm['preview'] is False)
check('I match scope = selection', match['scope'] == m10.SCOPE_SELECTION)
check('I match include-unnamed on', match['include_empty'] is True)
check('I match action = export', match['action'] == m10.ACTION_EXPORT)
check('I spell action = in-dialog list', spell['action'] == m10.ACTION_SPELL_LIST)
check('I launcher starts with nothing ticked', picked == [], repr(picked))

# Nothing ticked must be a clear message, not a silent no-op.
m11, vs11 = load(Doc([[dev('a')]]))
m11.ask_which_tools = lambda: []
m11.run_cc_tools()
check('I empty selection is explained',
      any('No tools selected' in a for a in vs11.alerts), repr(vs11.alerts))

# ── J: fuzz - a renamed device always keeps its associated partner ──────────
NAMES = ['amp1', 'AMP1', 'Amp1', 'cam 2', 'proc', 'PROC', 'spk 1', '',
         '<DEVICE>', 'PROC 2.02 FF ', 'proc 2.02 ff']
random.seed(20260823)
failures = []
for trial in range(1200):
    devs = [dev(random.choice(NAMES), random.choice(NAMES))
            for _ in range(random.randint(1, 4))]
    eqs = [equip(random.choice(NAMES)) for _ in range(random.randint(0, 3))]
    pcs = [pconn(random.choice(NAMES)) for _ in range(random.randint(0, 2))]
    assoc = {d: e for d, e in zip(devs, eqs) if random.random() < 0.7}

    mm, _vv = load(Doc([list(devs), list(eqs) + list(pcs)]), associations=assoc)

    def conn_links():
        return {(ci, di) for ci, c in enumerate(pcs)
                if not mm.is_unnamed(c.fields['ConnectedDev'])
                for di, d in enumerate(devs)
                if d.fields['name'] == c.fields['ConnectedDev']}

    before_conn = conn_links()
    scope = devs + eqs + pcs
    do_eq = random.choice([True, False])
    ed, _u, _s = mm.plan_renames(scope, True, do_eq, False, True, True)
    sy, _ua = mm.plan_link_sync(ed, {})
    sy = mm.dedupe_edits(ed, sy)
    if mm.find_socket_collisions(ed, {}):
        continue
    mm.apply_edits(ed + sy)

    renamed = set(e['handle'] for e in ed + sy
                  if e['kind'] == 'device' and e['is_link_name'])
    for d, e in assoc.items():
        if d in renamed and not mm.is_unnamed(d.fields['name']):
            if d.fields['name'] != e.fields['name']:
                failures.append(('renamed device lost its partner', trial,
                                 d.fields['name'], e.fields['name']))
    lost = before_conn - conn_links()
    if lost:
        failures.append(('connector reference lost', trial, lost, None))
    ed2, _u2, _s2 = mm.plan_renames(scope, True, do_eq, False, True, True)
    if ed2:
        failures.append(('not idempotent', trial,
                         [(e['old'], e['new']) for e in ed2[:2]], None))

check('J fuzz: 1200 docs, renamed devices keep their partner',
      not failures, repr(failures[:3]))

R.report_and_exit()
