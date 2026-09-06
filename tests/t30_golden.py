"""The curated device list.

Markdown rather than JSON on purpose: the same file goes to Claude alongside
JOB-SPEC.md, so the socket names it writes circuits against are the names the
plug-in builds. One source, so the two cannot disagree.
"""
import os
from harness import Doc, Results, load, dev

R = Results()
check = R.check
m, vs = load(Doc([[dev('x')]]))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIXTURE = '''# Some heading with no table

Prose that must be ignored, including a stray | pipe.

## Meyer Sound | TIGRA-L

A note about this device.

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN 1 | IN | LAN | EC-6A | L |
| LINE_THRU | OUT | LINE | XLR3F | R |

### Luminex | 10i-IP

| Connector | Side | Socket | Type | Signal |
|---|---|---|---|---|
| EC-6A | R | LAN 1 | OUT | LAN |

## Nobody | Nothing
'''

G = m.parse_golden_devices(FIXTURE)

# ── T1: structure ─────────────────────────────────────────────────────────
check('T1 two devices with sockets, one without',
      len(G) == 3, repr(sorted(G)))
tigra = G[(m.normalise_model('Meyer Sound'), m.normalise_model('TIGRA-L'))]
check('T1 sockets read in order',
      [s['socket'] for s in tigra['sockets']] == ['LAN_IN 1', 'LINE_THRU'],
      repr(tigra['sockets']))
check('T1 make and model kept verbatim',
      tigra['make'] == 'Meyer Sound' and tigra['model'] == 'TIGRA-L')
check('T1 prose between entries is ignored',
      all(v['make'] for v in G.values()), repr(G.keys()))
check('T1 a device with no table is kept but empty',
      G[(m.normalise_model('Nobody'), m.normalise_model('Nothing'))]['sockets'] == [])

# ── T2: columns matched by NAME, not position ─────────────────────────────
lum = G[(m.normalise_model('Luminex'), m.normalise_model('10i-IP'))]
spec = m.golden_socket_specs(lum)[0]
check('T2 a reordered table still reads correctly',
      spec == ('skt_R', 'LAN 1', 'OUT', 1, 'LAN', 'EC-6A'), repr(spec))

# ── T3: specs come out in builder shape ───────────────────────────────────
specs = m.golden_socket_specs(tigra)
check('T3 IN goes to the left edge',
      specs[0][0] == 'skt_L' and specs[0][3] == -1, repr(specs[0]))
check('T3 OUT goes to the right edge',
      specs[1][0] == 'skt_R' and specs[1][3] == 1, repr(specs[1]))
check('T3 signal and connector carried', specs[0][4] == 'LAN'
      and specs[0][5] == 'EC-6A', repr(specs[0]))

# ── T4: forgiving matching, same as everywhere else ──────────────────────
m._golden_cache.clear()
m._golden_cache.update(G)
for make, model in (('Meyer Sound', 'TIGRA-L'), ('meyer sound', 'tigra_l'),
                    ('MEYER-SOUND', 'TIGRA L')):
    check('T4 matches %r / %r' % (make, model),
          m.find_golden_device(make, model) is not None)
check('T4 an unknown device is not invented',
      m.find_golden_device('Acme', 'Widget') is None)
check('T4 a blank model never matches',
      m.find_golden_device('Meyer Sound', '') is None)

# ── T5: it beats the shipped database ─────────────────────────────────────
# The curated list is the house's answer; the shipped one is a fallback.
import inspect
build = inspect.getsource(m.build_job_devices)
check('T5 curated list consulted before the shipped database',
      build.index('find_golden_device') < build.index('find_db_device'),
      'order matters -- curated must win')
check('T5 both sit below the sockets the job lists',
      build.index('job_socket_specs') < build.index('find_golden_device'),
      'circuits reference those names, so they must win')

sizing = inspect.getsource(m.device_height)
check('T5 section sizing uses the same order',
      sizing.index('find_golden_device') < sizing.index('find_db_device'),
      'or a curated device is measured as if it had none')

# ── T6: a malformed file cannot take the tool down ───────────────────────
for junk in ('', '## no pipe here\n| Socket |\n', '|||||\n',
             '## A | B\n| Socket | Type |\n|---|---|\n| | |\n'):
    try:
        m.parse_golden_devices(junk)
        ok = True
    except Exception as err:
        ok = False
    check('T6 survives %r' % junk[:22], ok)
check('T6 a row with no socket name is dropped',
      m.parse_golden_devices('## A | B\n| Socket | Type |\n|---|---|\n| | IN |\n'
                             )[(m.normalise_model('A'), m.normalise_model('B'))
                               ]['sockets'] == [])
check('T6 a missing file is not an error',
      isinstance(m.load_golden_devices(), dict))

# ── T7: the shipped DEVICES.md is valid and clean ────────────────────────
shipped = os.path.join(ROOT, 'DEVICES.md')
check('T7 DEVICES.md exists', os.path.exists(shipped))
if os.path.exists(shipped):
    parsed = m.parse_golden_devices(open(shipped, encoding='utf-8').read())
    check('T7 it parses to real devices', len(parsed) >= 20, '%d' % len(parsed))
    check('T7 every entry has sockets',
          all(v['sockets'] for v in parsed.values()),
          repr([k for k, v in parsed.items() if not v['sockets']]))
    names = [s[1] for v in parsed.values() for s in m.golden_socket_specs(v)]
    check('T7 no socket name has stray whitespace',
          all(n == n.strip() for n in names),
          repr([n for n in names if n != n.strip()][:5]))
    check('T7 no socket name has a double space',
          not any('  ' in n for n in names),
          repr([n for n in names if '  ' in n][:5]))
    check('T7 every socket has a side',
          all(s[3] in (-1, 1) for v in parsed.values()
              for s in m.golden_socket_specs(v)))

R.report_and_exit()
