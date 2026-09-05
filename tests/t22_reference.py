"""Reference-exporter tests.

Turns an existing drawing into the JSON a generator would have to emit. The
part that matters is reading circuit wiring from ConnectCAD's stored
association rather than the cached Src_*/Dst_* fields, which go stale.
"""
import json
import os
from harness import Doc, Obj, Results, load, sock

R = Results()
check = R.check


def device(name, make='Meyer Sound', model='TIGRA-L', sockets=()):
    return Obj('Device', {
        'symbol': 'dev_label_generic', 'tag': name, 'name': name,
        'make': make, 'model': model, 'type': 'Generic',
        'loc_room': 'Grid', 'loc_rack': 'GRID PROCESSING RACK',
        'loc_rackU': '4',
    }, children=list(sockets))


def circ(signal='LAN', label='', src_cache='', dst_cache=''):
    return Obj('Circuit', {'Signal': signal, 'Label': label, 'Number': '',
                           'Src_Dev_Name': src_cache, 'Dst_Dev_Name': dst_cache})


# Devices carry their sockets in the PIO profile group, so the mock's children
# stand in for it.
spk = device('SPK 1.01 HL ARRAY 1', sockets=[sock('LAN_IN 1'), sock('LAN_THRU 1')])
swt = device('SWTCH 4.01 UPPER', 'Luminex', '10i-IP', sockets=[sock('LAN 1', 'OUT')])
c1 = circ('LAN', 'HL feed', src_cache='STALE NAME', dst_cache='ALSO STALE')

m, vs = load(Doc([[spk, swt, c1]]))
vs.GetCustomObjectProfileGroup = lambda h: h          # children are the group
vs.CC_GetCircuitSource = lambda c: (swt, swt.children[0], None, swt.children[0])
vs.CC_GetCircuitDest = lambda c: (spk, spk.children[0], None, spk.children[0])

ref = m.build_reference([spk, swt, c1])

# ── T1: devices and their sockets ───────────────────────────────────────────
check('T1 both devices exported', len(ref['devices']) == 2, repr(ref['devices']))
first = ref['devices'][0]
check('T1 name and model captured',
      first['name'] == 'SPK 1.01 HL ARRAY 1' and first['model'] == 'TIGRA-L',
      repr(first))
check('T1 sockets read from the profile group',
      [s['name'] for s in first['sockets']] == ['LAN_IN 1', 'LAN_THRU 1'],
      repr(first['sockets']))
check('T1 socket detail captured',
      first['sockets'][0]['signal'] == 'LAN'
      and first['sockets'][0]['connector'] == 'EC-6A', repr(first['sockets'][0]))
check('T1 location captured', first['rack'] == 'GRID PROCESSING RACK', repr(first))

# ── T2: wiring comes from the association, not the stale cache ──────────────
check('T2 circuit exported', len(ref['circuits']) == 1, repr(ref['circuits']))
wire = ref['circuits'][0]
check('T2 source from association, not Src_Dev_Name',
      wire['from']['device'] == 'SWTCH 4.01 UPPER', repr(wire['from']))
check('T2 destination from association',
      wire['to']['device'] == 'SPK 1.01 HL ARRAY 1', repr(wire['to']))
check('T2 socket ends captured',
      wire['from']['socket'] == 'LAN 1' and wire['to']['socket'] == 'LAN_IN 1',
      repr(wire))
check('T2 stale cache ignored entirely',
      'STALE NAME' not in json.dumps(ref), 'cache leaked into the export')

# ── T3: an unwired circuit is counted, not invented ─────────────────────────
c2 = circ('LAN', 'dangling')
m3, vs3 = load(Doc([[spk, c2]]))
vs3.GetCustomObjectProfileGroup = lambda h: h
vs3.CC_GetCircuitSource = lambda c: (None, None, None, None)
vs3.CC_GetCircuitDest = lambda c: (None, None, None, None)
ref3 = m3.build_reference([spk, c2])
check('T3 unwired circuit not exported as a connection', ref3['circuits'] == [],
      repr(ref3['circuits']))
check('T3 but it is counted', ref3['unwired_circuits'] == 1,
      repr(ref3['unwired_circuits']))

# ── T4: placeholders teach nothing and are dropped ──────────────────────────
blank = device('<DEVICE>', '', '')
m4, vs4 = load(Doc([[blank, spk]]))
vs4.GetCustomObjectProfileGroup = lambda h: h
ref4 = m4.build_reference([blank, spk])
check('T4 unnamed device INCLUDED, with an id',
      len(ref4['devices']) == 2, repr([d['id'] for d in ref4['devices']]))
unnamed_dev = [d for d in ref4['devices'] if d['unnamed']]
check('T4 flagged as unnamed', len(unnamed_dev) == 1, repr(unnamed_dev))
check('T4 given a referable id',
      unnamed_dev and unnamed_dev[0]['id'] == '<unnamed 1>',
      repr(unnamed_dev))
check('T4 counted', ref4['unnamed_devices'] == 1, repr(ref4['unnamed_devices']))

# ── T5: missing ConnectCAD routines degrade, never crash ────────────────────
m5, vs5 = load(Doc([[spk, c1]]))
for name in ('CC_GetCircuitSource', 'CC_GetCircuitDest',
             'GetCustomObjectProfileGroup'):
    if hasattr(vs5, name):
        delattr(vs5, name)
ref5 = m5.build_reference([spk, c1])
check('T5 still exports devices without the CC routines',
      len(ref5['devices']) == 1, repr(ref5['devices']))
check('T5 sockets simply empty, not an error',
      ref5['devices'][0]['sockets'] == [], repr(ref5['devices'][0]))

# ── T6: output is JSON, written under reference/ ────────────────────────────
path = m.save_reference(ref, 'Schematic')
check('T6 written under reference/',
      os.path.basename(os.path.dirname(path)) == m.REFERENCE_FOLDER, path)
with open(path, encoding='utf-8') as f:
    round_tripped = json.load(f)
check('T6 round-trips as JSON', round_tripped['devices'] == ref['devices'])
check('T6 filename carries the layer', 'Schematic' in os.path.basename(path), path)

# ── T7: a plan layer is reported as such, not silently empty ────────────────
m7, vs7 = load(Doc([[Obj('Room2D', {'name': 'Auditorium'})]]))
m7.ask_reference_options = lambda: {'scope': m7.SCOPE_DOCUMENT}
status, summary = m7.tool_export_reference()
check('T7 no-device export says wrong layer', 'wrong layer' in (summary or ''),
      repr(summary))
check('T7 and warns on screen',
      any('location plan' in a for a in vs7.alerts), repr(vs7.alerts))


# ── T8: an adapter end is captured, not read as unconnected ─────────────────
# The four handles are (device, device socket, adapter, terminal socket).
# Ignoring the adapter slot makes an adapted circuit look dangling.
adapter = Obj('Device', {'name': 'ADAPTER 1', 'tag': 'ADAPTER 1',
                         'make': 'Neutrik', 'model': 'NA2FPMF'})
c8 = circ('PWR')
m8, vs8 = load(Doc([[swt, spk, adapter, c8]]))
vs8.GetCustomObjectProfileGroup = lambda h: h
vs8.CC_GetCircuitSource = lambda c: (swt, swt.children[0], adapter,
                                     spk.children[0])
vs8.CC_GetCircuitDest = lambda c: (spk, spk.children[0], None, spk.children[0])
ref8 = m8.build_reference([swt, spk, adapter, c8])
wire8 = ref8['circuits'][0]
check('T8 adapter recorded', wire8['from'].get('adapter') == 'ADAPTER 1',
      repr(wire8['from']))
check('T8 device still resolved through the adapter',
      wire8['from']['device'] == 'SWTCH 4.01 UPPER', repr(wire8['from']))
check('T8 not counted as unwired', ref8['unwired_circuits'] == 0)

# ── T9: a circuit wired at one end only is surfaced ─────────────────────────
c9 = circ('PWR')
m9, vs9 = load(Doc([[spk, c9]]))
vs9.GetCustomObjectProfileGroup = lambda h: h
vs9.CC_GetCircuitSource = lambda c: (None, None, None, None)
vs9.CC_GetCircuitDest = lambda c: (spk, spk.children[0], None, spk.children[0])
ref9 = m9.build_reference([spk, c9])
check('T9 half-wired circuit still exported', len(ref9['circuits']) == 1)
check('T9 and flagged separately', len(ref9['half_wired_circuits']) == 1,
      repr(ref9['half_wired_circuits']))
check('T9 not counted as fully unwired', ref9['unwired_circuits'] == 0)

# ── T10: the documented one-arg call is tried first ─────────────────────────
calls = []
m10, vs10 = load(Doc([[spk, c9]]))
vs10.GetCustomObjectProfileGroup = lambda h: h


def one_arg_only(c):
    calls.append('one')
    return (spk, spk.children[0], None, spk.children[0])


vs10.CC_GetCircuitSource = one_arg_only
vs10.CC_GetCircuitDest = one_arg_only
m10.build_reference([spk, c9])
check('T10 one-argument form used', calls and calls[0] == 'one', repr(calls))


# ── T11: a circuit wired to an UNNAMED device is wired, not dangling ────────
# ConnectCAD parks unnamed devices at '<DEVICE>' -- one real drawing is half
# of them. Judging connectivity by whether a name came back reports real
# wiring as dangling, and points circuits at objects missing from the export.
nameless = Obj('Device', {'name': '<DEVICE>', 'tag': '', 'make': '', 'model': '',
                          'type': '', 'loc_room': '', 'loc_rack': '',
                          'loc_rackU': ''},
               children=[sock('Power In', 'IN', 'PWR', '---')])
c11 = circ('PWR')
m11, vs11 = load(Doc([[spk, nameless, c11]]))
vs11.GetCustomObjectProfileGroup = lambda h: h
vs11.CC_GetCircuitSource = lambda c: (nameless, nameless.children[0], None,
                                      nameless.children[0])
vs11.CC_GetCircuitDest = lambda c: (spk, spk.children[0], None, spk.children[0])
ref11 = m11.build_reference([spk, nameless, c11])

check('T11 not reported as half wired', ref11['half_wired_circuits'] == [],
      repr(ref11['half_wired_circuits']))
wire11 = ref11['circuits'][0]
check('T11 source marked connected', wire11['from'].get('connected') is True,
      repr(wire11['from']))
check('T11 source flagged as unnamed',
      wire11['from'].get('device_unnamed') is True, repr(wire11['from']))
check('T11 socket still read', wire11['from'].get('socket') == 'Power In',
      repr(wire11['from']))
check('T11 endpoint resolves to a device in the export',
      wire11['from']['device'] in [d['id'] for d in ref11['devices']],
      '%r not in %r' % (wire11['from'].get('device'),
                        [d['id'] for d in ref11['devices']]))

# ── T12: a genuinely absent end is still caught ─────────────────────────────
c12 = circ('PWR')
m12, vs12 = load(Doc([[spk, c12]]))
vs12.GetCustomObjectProfileGroup = lambda h: h
vs12.CC_GetCircuitSource = lambda c: (None, None, None, None)
vs12.CC_GetCircuitDest = lambda c: (spk, spk.children[0], None, spk.children[0])
ref12 = m12.build_reference([spk, c12])
check('T12 truly absent end still flagged',
      len(ref12['half_wired_circuits']) == 1, repr(ref12['half_wired_circuits']))
check('T12 and its source is None, not an empty name',
      ref12['circuits'][0]['from'] is None, repr(ref12['circuits'][0]))

R.report_and_exit()
