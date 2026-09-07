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

# ── T7: the shipped JOB-SPEC.md is valid and clean ───────────────────────
shipped = os.path.join(ROOT, 'JOB-SPEC.md')
check('T7 JOB-SPEC.md exists', os.path.exists(shipped))
if os.path.exists(shipped):
    parsed = m.parse_golden_devices(open(shipped, encoding='utf-8').read())
    check('T7 it parses to real devices', len(parsed) >= 20, '%d' % len(parsed))
    # Not every entry has sockets: devices known only from the rack layout
    # carry physical properties and no socket list yet. An entry with NEITHER
    # would be a parse failure.
    check('T7 every entry carries sockets or properties',
          all(v['sockets'] or v['properties'] for v in parsed.values()),
          repr([k for k, v in parsed.items()
                if not v['sockets'] and not v['properties']]))
    check('T7 most entries have sockets',
          sum(1 for v in parsed.values() if v['sockets']) >= 20)
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

# ── T8: physical properties ───────────────────────────────────────────────
PROPS = """## Focusrite | REDNET-D16R AES

- Width: 482.6 mm
- Height: 44.45 mm
- Weight: 3.84 kg
- Power: 30 W
- Rack mounted: yes
- Rack U: 1
- Nonsense: ignored

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| AES_IN | IN | AES | XLR3M | L |

## Meyer Sound | TIGRA-L

- Width:
- Weight: -

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN 1 | IN | LAN | EC-6A | L |
"""
P = m.parse_golden_devices(PROPS)
fr = P[(m.normalise_model('Focusrite'), m.normalise_model('REDNET-D16R AES'))]

check('T8 properties read', m.golden_property(fr, 'width') == '482.6 mm',
      repr(fr['properties']))
check('T8 units are kept, not stripped',
      'mm' in m.golden_property(fr, 'width')
      and 'kg' in m.golden_property(fr, 'weight'), repr(fr['properties']))
check('T8 a number can still be pulled out',
      m.golden_number(fr, 'width') == 482.6 and m.golden_number(fr, 'power') == 30.0,
      repr((m.golden_number(fr, 'width'), m.golden_number(fr, 'power'))))
check('T8 rack mounted reads as a boolean',
      m.golden_is_rack_mounted(fr) is True)
check('T8 rack U is the size in U', m.golden_number(fr, 'rack u') == 1.0)
check('T8 an unrecognised key is ignored',
      'nonsense' not in fr['properties'], repr(fr['properties']))
check('T8 properties do not break the socket table',
      len(fr['sockets']) == 1, repr(fr['sockets']))

# Blank and placeholder values must not become data.
tig = P[(m.normalise_model('Meyer Sound'), m.normalise_model('TIGRA-L'))]
check('T8 an empty property is not recorded', tig['properties'] == {},
      repr(tig['properties']))
check('T8 a dash placeholder is not recorded',
      m.golden_property(tig, 'weight') == '')
check('T8 unknown reads as None, not False',
      m.golden_is_rack_mounted(tig) is None)
check('T8 a missing number is None', m.golden_number(tig, 'width') is None)
check('T8 a device with no properties still has its sockets',
      len(tig['sockets']) == 1)

# ── T9: the shipped file leaves unknowns blank ───────────────────────────
if os.path.exists(shipped):
    with_props = [k for k, v in parsed.items() if v['properties']]
    check('T9 some devices carry real physical data', len(with_props) >= 2,
          '%d of %d' % (len(with_props), len(parsed)))
    check('T9 the rest are blank rather than invented',
          len(with_props) < len(parsed),
          'every device has properties, which would mean they were guessed')
    for key, entry in parsed.items():
        for prop, value in entry['properties'].items():
            check('T9 %s %s has a unit or is a count' % (key[1][:14], prop),
                  prop in ('rack mounted', 'rack u')
                  or any(c.isalpha() for c in value),
                  repr(value))

# ── T10: the measured data is internally consistent ──────────────────────
# Rack height and rack U come from different fields of the drawing, so they
# are an independent check on each other -- and on the feet-to-inches
# conversion used to seed the file.
if os.path.exists(shipped):
    checked = 0
    for key, entry in parsed.items():
        h = m.golden_number(entry, 'height')
        u = m.golden_number(entry, 'rack u')
        if h is None or u is None or not m.golden_is_rack_mounted(entry):
            continue
        checked += 1
        check('T10 %s: %gU x 1.75 in = its height' % (key[1][:18], u),
              abs(h - u * 1.75) < 0.06, 'height %s, %s U' % (h, u))
    check('T10 several devices were cross-checked', checked >= 5, '%d' % checked)

# ── T11: one file carries the spec AND the device list ───────────────────
# They were merged so a user hands Claude a single file. The risk is the
# spec's own markdown tables being read as device sockets.
FENCED = """# A spec with examples

The format looks like this:

```
## Example Make | Example Model

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| NOT_REAL | IN | LAN | EC-6A | L |
```

### Devices

| Key | Required | Meaning |
|---|---|---|
| name | yes | the link key |

---

## Real Make | Real Model

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| IN 1 | IN | LINE | XLR3M | L |
"""
F = m.parse_golden_devices(FENCED)
check('T11 a device inside a code fence is not real',
      (m.normalise_model('Example Make'),
       m.normalise_model('Example Model')) not in F, repr(sorted(F)))
check('T11 the real device is found', len(F) == 1, repr(sorted(F)))
real = F[(m.normalise_model('Real Make'), m.normalise_model('Real Model'))]
check('T11 a spec table before it is not absorbed',
      [s['socket'] for s in real['sockets']] == ['IN 1'],
      repr(real['sockets']))
check('T11 tildes fence too',
      len(m.parse_golden_devices('~~~\n## A | B\n~~~\n')) == 0)

# The shipped file must survive the same trap.
if os.path.exists(shipped):
    junk = {'Key', 'Socket', 'Required', 'Meaning', 'name', 'signal', 'cable'}
    polluted = [k for k, v in parsed.items()
                if any(s['socket'] in junk for s in v['sockets'])]
    check('T11 the shipped file has no spec tables in its devices',
          not polluted, repr(polluted))
    check('T11 no device named from a fenced example',
          not any('example' in (k[0] + k[1]) for k in parsed), repr(sorted(parsed)[:3]))

# ── T12: either filename is accepted ─────────────────────────────────────
import tempfile
for name in ('devices.md', 'JOB-SPEC.md', 'job-spec.md'):
    d = tempfile.mkdtemp()
    m.BASE_FOLDER = d
    with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
        f.write('## A | B\n\n| Socket | Type |\n|---|---|\n| X | IN |\n')
    # Compared case-insensitively: macOS matches JOB-SPEC.md for a lookup of
    # job-spec.md, so the path comes back in whichever casing the candidate
    # list tried first. Both spellings stay in the list for case-sensitive
    # filesystems, where they are genuinely different files.
    check('T12 %s is found' % name,
          os.path.basename(m.golden_path()).lower() == name.lower(),
          m.golden_path())
    m._golden_cache.clear()
    check('T12 %s parses' % name, len(m.load_golden_devices()) == 1)
m.BASE_FOLDER = tempfile.mkdtemp()
check('T12 a missing file returns the default name',
      m.golden_path().endswith('devices.md'), m.golden_path())

R.report_and_exit()
