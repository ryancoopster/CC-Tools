"""Preferences, sections, and the repeated-device convention.

The drawings these jobs land in divide one design layer into bands by signal
type, and a physical device is DRAWN AGAIN in each band it appears in. So
device names repeat by design, which is why ids exist: names identify the
ConnectCAD object, ids identify the block in the job.
"""
import json
import os
from harness import Doc, Results, load, dev

R = Results()
check = R.check
GY = GX = 0.25


def d(ident, name=None, section=None, column=0, sockets=None, align=None):
    device = {'name': name or ident, 'column': column,
              'sockets': sockets or [{'name': 'IN 1', 'type': 'IN', 'side': 'L'},
                                     {'name': 'OUT 1', 'type': 'OUT', 'side': 'R'}]}
    if ident != (name or ident):
        device['id'] = ident
    if section is not None:
        device['section'] = section
    if align:
        device['align_to'] = align
    return device


m, vs = load(Doc([[dev('x')]]))
m.BASE_FOLDER = os.path.join(m.BASE_FOLDER, 'prefs')
os.makedirs(m.BASE_FOLDER, exist_ok=True)


def write_prefs(payload):
    with open(m.prefs_path(), 'w', encoding='utf-8') as f:
        f.write(payload if isinstance(payload, str) else json.dumps(payload))


# ── T1: preferences round-trip, and survive damage ─────────────────────────
if os.path.exists(m.prefs_path()):
    os.remove(m.prefs_path())
check('T1 defaults when no file', m.load_prefs() == m.PREF_DEFAULTS)

m.save_prefs(dict(m.PREF_DEFAULTS, column_inches=6.0, circuit_type='rounded'))
back = m.load_prefs()
check('T1 saved values come back',
      back['column_inches'] == 6.0 and back['circuit_type'] == 'rounded', repr(back))

write_prefs('{ this is not json')
check('T1 corrupt file falls back to defaults', m.load_prefs() == m.PREF_DEFAULTS)

write_prefs({'column_inches': 6.0, 'row_inches': 'not a number'})
back = m.load_prefs()
check('T1 one bad key does not discard the good ones',
      back['column_inches'] == 6.0
      and back['row_inches'] == m.PREF_DEFAULTS['row_inches'], repr(back))

write_prefs({'column_inches': 0.0})
check('T1 out-of-range value rejected',
      m.load_prefs()['column_inches'] == m.PREF_DEFAULTS['column_inches'])

write_prefs({'column_inches': 99999.0})
check('T1 absurdly large value rejected',
      m.load_prefs()['column_inches'] == m.PREF_DEFAULTS['column_inches'])
os.remove(m.prefs_path())

# ── T2: column and row spacing actually move devices ───────────────────────
job = {'devices': [d('A', column=0), d('B', column=1)], 'circuits': []}
wide = dict(m.PREF_DEFAULTS, column_inches=8.0)
narrow = dict(m.PREF_DEFAULTS, column_inches=2.0)
check('T2 column spacing is honoured',
      m.job_position(job['devices'][1], GX, GY, wide)[0]
      == 4 * m.job_position(job['devices'][1], GX, GY, narrow)[0],
      repr((m.job_position(job['devices'][1], GX, GY, wide),
            m.job_position(job['devices'][1], GX, GY, narrow))))

rowy = {'name': 'R', 'row': 2, 'sockets': []}
tall = dict(m.PREF_DEFAULTS, row_inches=5.0)
check('T2 row spacing is honoured',
      m.job_position(rowy, GX, GY, tall)[1]
      == 2 * m.job_position(rowy, GX, GY, m.PREF_DEFAULTS)[1],
      repr(m.job_position(rowy, GX, GY, tall)))

# ── T3: a device drawn again in another section is legal ──────────────────
job = {
    'sections': [{'name': 'Analog'}, {'name': 'Power'}],
    'devices': [
        d('spk-analog', 'SPK 1.01', section='Analog'),
        d('spk-power', 'SPK 1.01', section='Power'),
    ],
    'circuits': [],
}
os.makedirs(m.BASE_FOLDER, exist_ok=True)
with open(m.job_path(), 'w', encoding='utf-8') as f:
    json.dump(job, f)
parsed, problems = m.read_job()
check('T3 repeated NAME across sections is accepted', problems == [], repr(problems))
check('T3 both blocks kept', len(parsed['devices']) == 2)

# With no ids at all, both fall back to the same name and become ambiguous --
# a circuit naming "SPK 1.01" could not say which block it meant.
job['devices'][0].pop('id')
job['devices'][1].pop('id')
with open(m.job_path(), 'w', encoding='utf-8') as f:
    json.dump(job, f)
_p, problems = m.read_job()
check('T3 repeated name with no ids IS an error',
      any('share the id' in x for x in problems), repr(problems))

# ── T4: sections stack as bands, in order, without overlapping ─────────────
job = {
    'sections': [{'name': 'Analog'}, {'name': 'Power'}],
    'devices': [
        d('a1', 'A1', section='Analog'),
        d('a2', 'A2', section='Analog', column=1),
        d('p1', 'P1', section='Power'),
    ],
    'circuits': [],
}
prefs = dict(m.PREF_DEFAULTS, section_gap_inches=3.0)
pos, notes = m.resolve_job_positions(job, GX, GY, 1.0, 1.0, prefs)
check('T4 no complaints', notes == [], repr(notes))

analog = [job['devices'][0], job['devices'][1]]
power = [job['devices'][2]]
a_top, a_bottom = m.section_extent(analog, pos, 1.0, 1.0, GY)
p_top, p_bottom = m.section_extent(power, pos, 1.0, 1.0, GY)
check('T4 first section starts at the top', a_top == 0.0, repr(a_top))
check('T4 second section sits below the first', p_top < a_bottom,
      'analog bottom %s, power top %s' % (a_bottom, p_top))
check('T4 gap is exactly the preference', abs((a_bottom - p_top) - 3.0) < 1e-9,
      repr(a_bottom - p_top))

bigger = dict(m.PREF_DEFAULTS, section_gap_inches=10.0)
pos2, _n = m.resolve_job_positions(job, GX, GY, 1.0, 1.0, bigger)
_t2, _b2 = m.section_extent(analog, pos2, 1.0, 1.0, GY)
check('T4 a larger gap pushes the second section further down',
      m.section_extent(power, pos2, 1.0, 1.0, GY)[0] < p_top,
      repr(m.section_extent(power, pos2, 1.0, 1.0, GY)))

# ── T5: alignment still works inside a section, and cannot cross one ───────
job = {
    'sections': [{'name': 'One'}, {'name': 'Two'}],
    'devices': [
        d('src', 'SRC', section='One',
          sockets=[{'name': 'O1', 'type': 'OUT', 'side': 'R'},
                   {'name': 'O2', 'type': 'OUT', 'side': 'R'}]),
        d('dst', 'DST', section='One', column=1,
          align={'device': 'src', 'socket': 'O2', 'my_socket': 'I1'},
          sockets=[{'name': 'I1', 'type': 'IN', 'side': 'L'}]),
        d('far', 'FAR', section='Two', column=1,
          align={'device': 'src', 'socket': 'O1', 'my_socket': 'I1'},
          sockets=[{'name': 'I1', 'type': 'IN', 'side': 'L'}]),
    ],
    'circuits': [],
}
pos, notes = m.resolve_job_positions(job, GX, GY, 1.0, 1.0, m.PREF_DEFAULTS)


def socket_y(ident, device, socket):
    i, _s = m.socket_stack_index(device, socket)
    return pos[ident][1] - m.socket_drop(i, 1.0, 1.0, GY)


check('T5 alignment inside a section still lines up',
      abs(socket_y('src', job['devices'][0], 'O2')
          - socket_y('dst', job['devices'][1], 'I1')) < 1e-9,
      repr((socket_y('src', job['devices'][0], 'O2'),
            socket_y('dst', job['devices'][1], 'I1'))))
check('T5 cross-section align_to is reported',
      any('not in this section' in n for n in notes), repr(notes))

# ── T6: a circuit across two sections can never wire, so it is an error ────
job = {
    'sections': [{'name': 'One'}, {'name': 'Two'}],
    'devices': [d('a', 'A', section='One'), d('b', 'B', section='Two')],
    'circuits': [{'from': {'device': 'a', 'socket': 'OUT 1'},
                  'to': {'device': 'b', 'socket': 'IN 1'}}],
}
with open(m.job_path(), 'w', encoding='utf-8') as f:
    json.dump(job, f)
_p, problems = m.read_job()
check('T6 cross-section circuit rejected',
      any('separate regions' in x for x in problems), repr(problems))

job['devices'][1]['section'] = 'One'
with open(m.job_path(), 'w', encoding='utf-8') as f:
    json.dump(job, f)
_p, problems = m.read_job()
check('T6 same-section circuit is fine', problems == [], repr(problems))

# ── T7: circuits reference ids, and wiring verifies by COUNT ──────────────
# Two identical-looking circuits between two devices that share a name must
# need two real circuits, not one found twice.
job = {
    'devices': [d('s1', 'SPK', section='A'), d('s2', 'SPK', section='B')],
    'circuits': [],
}
with open(m.job_path(), 'w', encoding='utf-8') as f:
    json.dump(job, f)
parsed, problems = m.read_job()
check('T7 two blocks may share a name given distinct ids', problems == [],
      repr(problems))
ids = [m.job_device_id(x) for x in parsed['devices']]
check('T7 ids are what distinguishes them', ids == ['s1', 's2'], repr(ids))
check('T7 id falls back to the name when absent',
      m.job_device_id({'name': 'ONLY'}) == 'ONLY')

# ── T8: circuit fields are written onto the object ────────────────────────
# Wire numbers are deliberately NOT written: ConnectCAD numbers by signal type
# and a second scheme fighting it would be worse than none.
from mockvs import Obj

plain = dict(m.PREF_DEFAULTS)
circ = Obj('Circuit', {'Signal': 'AVB Pri', 'Number': 'CC-7', 'Cable': '',
                       'Label': '', 'CircuitType': 'polyline'})
written = m.finish_circuit(circ, {'signal': 'MILAN PRI', 'cable': 'SPK1 NET'},
                           plain)
check('T8 signal written', circ.fields['Signal'] == 'MILAN PRI', repr(circ.fields))
check('T8 cable written', circ.fields['Cable'] == 'SPK1 NET', repr(circ.fields))
check('T8 ConnectCAD\'s own wire number left alone',
      circ.fields['Number'] == 'CC-7', repr(circ.fields))
check('T8 reports what it wrote', set(written) == {'Signal', 'Cable'},
      repr(written))
check('T8 line mode untouched when the preference is blank',
      circ.fields['CircuitType'] == 'polyline', repr(circ.fields))

circ2 = Obj('Circuit', {'Signal': '', 'Number': '', 'Cable': '', 'Label': '',
                        'CircuitType': 'polyline'})
m.finish_circuit(circ2, {'signal': 'PWR'}, dict(plain, circuit_type='rounded'))
check('T8 line mode applied when the preference is set',
      circ2.fields['CircuitType'] == 'rounded', repr(circ2.fields))

circ3 = Obj('Circuit', {'Signal': 'KEEP', 'Number': '', 'Cable': 'KEEP',
                        'Label': '', 'CircuitType': ''})
check('T8 a circuit the job says nothing about is not touched',
      m.finish_circuit(circ3, {}, plain) == []
      and circ3.fields['Signal'] == 'KEEP' and circ3.fields['Cable'] == 'KEEP',
      repr(circ3.fields))

check('T8 no numbering preferences remain',
      not any('number' in k for k in m.PREF_DEFAULTS), repr(m.PREF_DEFAULTS))

# ── T9: a symbol device is sized by its SYMBOL, not by the job ────────────
# The job lists no sockets for a symbol device -- the symbol already has them
# placed. Measuring the empty list would report a short device and let the
# next section overlap it.
CATALOGUE = [{'symbol': 'Meyer_TIGRA-L', 'make': 'Meyer Sound',
              'model': 'TIGRA-L', 'sockets': 4, 'height': 9.0,
              'handle': 'SYM1', 'folder': 'zConnectCAD db Created'}]

symbol_device = {'name': 'BIG', 'make': 'Meyer Sound', 'model': 'TIGRA-L',
                 'sockets': []}
check('T9 symbol height used when a symbol matches',
      m.device_height(symbol_device, 1.0, 1.0, GY, CATALOGUE) == 9.0,
      repr(m.device_height(symbol_device, 1.0, 1.0, GY, CATALOGUE)))
check('T9 falls back to the socket list with no catalogue',
      m.device_height(symbol_device, 1.0, 1.0, GY, None)
      == m.body_height_for([], 1.0, 1.0, GY))
check('T9 a device with no matching symbol still measures its sockets',
      m.device_height({'name': 'X', 'make': 'Nobody', 'model': 'Nothing',
                       'sockets': [{'name': 'A', 'side': 'L'}]},
                      1.0, 1.0, GY, CATALOGUE)
      == m.body_height_for([('skt_L', 'A', 'IO', -1, '', '')], 1.0, 1.0, GY))

# A tall symbol device must push the next section clear of it.
job = {
    'sections': [{'name': 'Top'}, {'name': 'Below'}],
    'devices': [
        {'id': 'big', 'name': 'BIG', 'make': 'Meyer Sound', 'model': 'TIGRA-L',
         'section': 'Top', 'column': 0, 'sockets': []},
        d('small', 'SMALL', section='Below'),
    ],
    'circuits': [],
}
gap = dict(m.PREF_DEFAULTS, section_gap_inches=1.0)
pos, _n = m.resolve_job_positions(job, GX, GY, 1.0, 1.0, gap, CATALOGUE)
top_bottom = m.section_extent([job['devices'][0]], pos, 1.0, 1.0, GY, CATALOGUE)[1]
below_top = m.section_extent([job['devices'][1]], pos, 1.0, 1.0, GY, CATALOGUE)[0]
check('T9 the section below clears a 9-unit-tall symbol device',
      below_top < top_bottom and abs((top_bottom - below_top) - 1.0) < 1e-9,
      'symbol bottom %s, next top %s' % (top_bottom, below_top))

# Without the catalogue the same job would have overlapped, which is the bug.
pos_blind, _n = m.resolve_job_positions(job, GX, GY, 1.0, 1.0, gap, None)
blind_top = m.section_extent([job['devices'][1]], pos_blind, 1.0, 1.0, GY, None)[0]
check('T9 without symbol heights the sections would have collided',
      blind_top > top_bottom,
      'blind next-top %s vs real symbol bottom %s' % (blind_top, top_bottom))

# ── T10: only the four real line modes, and arrows are left alone ─────────
# 'direct' and 'orthogonal' were in this list once. They were invented; the
# legal set is polyline / rounded / chamfer / arrow, and 'arrow' is excluded
# because it is a different object, not a different corner style.
check('T10 no invented line modes',
      'direct' not in m.CIRCUIT_TYPES and 'orthogonal' not in m.CIRCUIT_TYPES,
      repr(m.CIRCUIT_TYPES))
check('T10 the three routed modes are offered',
      set(m.CIRCUIT_TYPES) == {'', 'rounded', 'polyline', 'chamfer'},
      repr(m.CIRCUIT_TYPES))
check('T10 arrow is not offered as a line mode',
      'arrow' not in m.CIRCUIT_TYPES, repr(m.CIRCUIT_TYPES))

arrow = Obj('Circuit', {'Signal': '', 'Number': '', 'Cable': '', 'Label': '',
                        'CircuitType': 'arrow'})
m.finish_circuit(arrow, {'signal': 'PWR'}, dict(m.PREF_DEFAULTS,
                                                circuit_type='rounded'))
check('T10 an arrow circuit is never converted',
      arrow.fields['CircuitType'] == 'arrow', repr(arrow.fields))

routed = Obj('Circuit', {'Signal': '', 'Number': '', 'Cable': '', 'Label': '',
                         'CircuitType': 'polyline'})
m.finish_circuit(routed, {'signal': 'PWR'}, dict(m.PREF_DEFAULTS,
                                                 circuit_type='rounded'))
check('T10 a routed circuit still converts',
      routed.fields['CircuitType'] == 'rounded', repr(routed.fields))

R.report_and_exit()
