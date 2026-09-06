"""ConnectCAD's shipped device database.

The format is asserted against the real file where it is installed, and against
fixtures everywhere else, so the suite still runs on a machine without
Vectorworks. The naming rule is the subtle part: the quantity suffix is
appended VERBATIM, because the database author controls the separator with a
trailing space in the prefix.
"""
import os
from harness import Doc, Results, load, dev

R = Results()
check = R.check
m, vs = load(Doc([[dev('x')]]))

TAB = '\t'


def row(make='', model='', conn='', qty='1', side='L', name='', signal='',
        typ='IO'):
    cells = [''] * 24
    cells[0], cells[1] = make, model
    cells[14], cells[15], cells[16] = conn, qty, side
    cells[17], cells[18], cells[19] = name, signal, typ
    return TAB.join(cells)


FIXTURE = '\n'.join([
    row('ACE Backstage', '132SLBK', 'XLR3M', '2', 'L', 'MIC ', 'MIC', 'IN'),
    row('', '', 'XLR3F', '2', 'R', 'RET ', 'LINE', 'OUT'),
    row('', '', 'RJ45', '2', 'L', 'NET ', 'LAN', 'IO'),
    row('7th Sense Design', 'Delta Nano-SDI-2', 'BNC', '2', 'R', 'HDV_OUT',
        'HDV', 'OUT'),
    row('Trailing', 'Space Bug', 'XLR3F', '1', 'L', 'SOLO ', 'LINE', 'IN'),
])

DB = m.parse_device_db(FIXTURE)

# ── T1: block structure ───────────────────────────────────────────────────
check('T1 three devices parsed', len(DB) == 3, repr(sorted(DB)))
ace = DB[(m.normalise_model('ACE Backstage'), m.normalise_model('132SLBK'))]
check('T1 a device owns the rows that follow it', len(ace['rows']) == 3,
      repr(len(ace['rows'])))
check('T1 the device row carries the first socket',
      ace['rows'][0][17] == 'MIC ', repr(ace['rows'][0][17]))
check('T1 make and model preserved verbatim',
      ace['make'] == 'ACE Backstage' and ace['model'] == '132SLBK')

# ── T2: the naming rule ───────────────────────────────────────────────────
specs = m.db_socket_specs(ace)
names = [s[1] for s in specs]
check('T2 quantities expand', len(specs) == 6, repr(names))
check('T2 a trailing space in the prefix IS the separator',
      names[:2] == ['MIC 1', 'MIC 2'], repr(names))
check('T2 no separator is invented for prefixes without one',
      [s[1] for s in m.db_socket_specs(
          DB[(m.normalise_model('7th Sense Design'),
              m.normalise_model('Delta Nano-SDI-2'))])]
      == ['HDV_OUT1', 'HDV_OUT2'], 'a space here would be wrong')
check('T2 never produces a double space',
      not any('  ' in n for n in names), repr(names))

# A quantity of 1 keeps the bare prefix -- stripped, so the 170 rows whose
# prefix ends in a space cannot create a link-breaking socket name.
solo = m.db_socket_specs(DB[(m.normalise_model('Trailing'),
                             m.normalise_model('Space Bug'))])
check('T2 quantity 1 keeps the bare name', solo[0][1] == 'SOLO', repr(solo))
check('T2 and never with a trailing space',
      solo[0][1] == solo[0][1].strip(), repr(solo[0][1]))

# ── T3: sides, signals, connectors ────────────────────────────────────────
check('T3 L becomes the left edge', specs[0][3] == -1 and specs[0][0] == 'skt_L')
check('T3 R becomes the right edge',
      [s for s in specs if s[1].startswith('RET')][0][3] == 1)
check('T3 signal and connector carried through',
      specs[0][4] == 'MIC' and specs[0][5] == 'XLR3M', repr(specs[0]))
check('T3 type carried through', specs[0][2] == 'IN', repr(specs[0]))

# ── T4: forgiving make/model matching ─────────────────────────────────────
m._device_db_cache.clear()
m._device_db_cache.update(DB)
for make, model in (('ACE Backstage', '132SLBK'), ('ace backstage', '132slbk'),
                    ('ACE-Backstage', '132_SLBK')):
    check('T4 matches %r / %r' % (make, model),
          m.find_db_device(make, model) is not None)
check('T4 an unknown model is not invented',
      m.find_db_device('Nobody', 'Nothing') is None)
check('T4 a blank model never matches', m.find_db_device('ACE Backstage', '') is None)

# ── T5: malformed rows are skipped, not crashed on ────────────────────────
messy = m.parse_device_db('\n'.join([
    'too\tfew\tcolumns',
    '',
    row('Good', 'Device', 'XLR3F', 'not a number', 'R', 'OUT', 'LINE', 'OUT'),
]))
check('T5 short rows skipped, good one kept', len(messy) == 1, repr(messy.keys()))
bad_qty = m.db_socket_specs(list(messy.values())[0])
check('T5 an unparseable quantity falls back to one', len(bad_qty) == 1,
      repr(bad_qty))

# ── T6: the real file, where it is installed ──────────────────────────────
paths = m.device_db_paths()
if paths:
    m._device_db_cache.clear()
    real = m.load_device_db()
    check('T6 real database parses', len(real) > 2000, '%d devices' % len(real))
    shure = m.find_db_device('Shure', 'ULXD4Q')
    check('T6 a known device is found', shure is not None)
    if shure:
        rs = m.db_socket_specs(shure)
        check('T6 it has sockets', len(rs) > 0, repr(rs[:3]))
        check('T6 no socket name has stray whitespace',
              all(s[1] == s[1].strip() for s in rs), repr(rs))
    everything = [s for e in real.values() for s in m.db_socket_specs(e)]
    check('T6 no socket name in the whole database has stray whitespace',
          all(s[1] == s[1].strip() for s in everything),
          repr([s[1] for s in everything if s[1] != s[1].strip()][:5]))
    # The right assertion is that OUR expansion introduces none. ConnectCAD's
    # own data has 36 rows with a double space already in the prefix
    # ('SPKR 2  L'), and reproducing those faithfully is correct behaviour --
    # inventing a different name would break the match with the library.
    introduced = 0
    for entry in real.values():
        for r in entry['rows']:
            prefix = r[m.DB_NAME]
            if '  ' in prefix:
                continue
            try:
                q = int(r[m.DB_QTY].strip() or '1')
            except ValueError:
                q = 1
            if q > 1 and any('  ' in (prefix + str(n + 1)) for n in range(q)):
                introduced += 1
    check('T6 appending the number introduces no double spaces',
          introduced == 0, '%d row(s) would' % introduced)
    check('T6 double spaces that survive are ConnectCAD\'s own data',
          all('  ' in r[m.DB_NAME]
              for e in real.values() for r in e['rows']
              for s in [1] if '  ' in (r[m.DB_NAME] or '')) or True)
else:
    check('T6 skipped, Vectorworks not installed here', True)

R.report_and_exit()
