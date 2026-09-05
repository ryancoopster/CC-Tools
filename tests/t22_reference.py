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
vs.CC_GetCircuitSource = lambda c, skip: (swt, None, None, swt.children[0])
vs.CC_GetCircuitDest = lambda c, skip: (spk, None, None, spk.children[0])

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
vs3.CC_GetCircuitSource = lambda c, skip: (None, None, None, None)
vs3.CC_GetCircuitDest = lambda c, skip: (None, None, None, None)
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
check('T4 unnamed device excluded',
      all(d['name'] != '<DEVICE>' for d in ref4['devices']),
      repr([d['name'] for d in ref4['devices']]))

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

R.report_and_exit()
