"""Job layout: the file picker, and the geometry that decides wiring.

ConnectCAD only joins sockets at the same height, so these are not cosmetic
checks -- a device a quarter inch out draws perfectly and wires to nothing.
The alignment numbers here are cross-checked against a live drawing, where
socket drops were measured at 0.5 / 0.75 / 1.0 below the header.
"""
import json
import os
from harness import Doc, Results, load, dev

R = Results()
check = R.check

GY = GX = 0.25          # the grid a real schematic layer reports


def spk(name, align=None, sockets=None):
    device = {'name': name, 'make': 'Meyer Sound', 'model': 'TIGRA-L',
              'column': 1,
              'sockets': sockets or [
                  {'name': 'LAN_IN 1', 'type': 'IN', 'side': 'L'},
                  {'name': 'LAN_THRU 1', 'type': 'OUT', 'side': 'R'}]}
    if align:
        device['align_to'] = align
    return device


SWITCH = {
    'name': 'SWTCH', 'make': 'Luminex', 'model': '10i-IP',
    'column': 0, 'row': 0,
    'sockets': [{'name': 'LAN 1', 'type': 'OUT', 'side': 'R'},
                {'name': 'LAN 2', 'type': 'OUT', 'side': 'R'},
                {'name': 'LAN 3', 'type': 'OUT', 'side': 'R'}],
}

m, vs = load(Doc([[dev('x')]]))


def socket_y(m, positions, device, socket_name):
    """Document y of a socket, the way the drawing code computes it."""
    index, _side = m.socket_stack_index(device, socket_name)
    return positions[device['name']][1] - m.socket_drop(index, 1.0, 1.0, GY)


# ── T1: sockets are numbered per EDGE, not per device ───────────────────────
mixed = spk('M', sockets=[
    {'name': 'IN A', 'side': 'L'}, {'name': 'OUT A', 'side': 'R'},
    {'name': 'IN B', 'side': 'L'}, {'name': 'OUT B', 'side': 'R'}])
check('T1 left stack starts at 0', m.socket_stack_index(mixed, 'IN A') == (0, -1),
      repr(m.socket_stack_index(mixed, 'IN A')))
check('T1 right stack also starts at 0',
      m.socket_stack_index(mixed, 'OUT A') == (0, 1),
      repr(m.socket_stack_index(mixed, 'OUT A')))
check('T1 second on each edge is index 1',
      m.socket_stack_index(mixed, 'IN B') == (1, -1)
      and m.socket_stack_index(mixed, 'OUT B') == (1, 1))
check('T1 unknown socket reports nothing',
      m.socket_stack_index(mixed, 'NOPE') == (None, None))

# ── T2: y is the device TOP, so socket height ignores socket count ──────────
# The regression this guards: anchoring on the bottom made a device's header
# move as sockets were added, so two devices written at the same y only lined
# up when they happened to have the same number of sockets.
one = {'name': 'ONE', 'x': 0, 'y': 0,
       'sockets': [{'name': 'A', 'side': 'L'}]}
many = {'name': 'MANY', 'x': 4, 'y': 0,
        'sockets': [{'name': 'A', 'side': 'L'}, {'name': 'B', 'side': 'L'},
                    {'name': 'C', 'side': 'L'}, {'name': 'D', 'side': 'L'}]}
job = {'devices': [one, many], 'circuits': []}
pos, notes = m.resolve_job_positions(job, GX, GY)
check('T2 same y regardless of socket count',
      socket_y(m, pos, one, 'A') == socket_y(m, pos, many, 'A'),
      '%s vs %s' % (socket_y(m, pos, one, 'A'), socket_y(m, pos, many, 'A')))
check('T2 bodies still differ in height',
      m.body_height_for(m.job_socket_specs(many), 1.0, 1.0, GY)
      > m.body_height_for(m.job_socket_specs(one), 1.0, 1.0, GY))

# ── T3: align_to lines the named sockets up exactly ────────────────────────
job = {'devices': [
    SWITCH,
    spk('A', {'device': 'SWTCH', 'socket': 'LAN 1', 'my_socket': 'LAN_IN 1'}),
    spk('B', {'device': 'SWTCH', 'socket': 'LAN 2', 'my_socket': 'LAN_IN 1'}),
    spk('C', {'device': 'SWTCH', 'socket': 'LAN 3', 'my_socket': 'LAN_IN 1'}),
], 'circuits': []}
pos, notes = m.resolve_job_positions(job, GX, GY)
check('T3 no complaints', notes == [], repr(notes))
for letter, out in (('A', 'LAN 1'), ('B', 'LAN 2'), ('C', 'LAN 3')):
    target = [d for d in job['devices'] if d['name'] == letter][0]
    check('T3 %s lines up with %s' % (letter, out),
          abs(socket_y(m, pos, SWITCH, out)
              - socket_y(m, pos, target, 'LAN_IN 1')) < 1e-9,
          '%s vs %s' % (socket_y(m, pos, SWITCH, out),
                        socket_y(m, pos, target, 'LAN_IN 1')))
check('T3 drops match the live drawing (0.5/0.75/1.0)',
      [round(socket_y(m, pos, SWITCH, s), 4)
       for s in ('LAN 1', 'LAN 2', 'LAN 3')] == [-0.5, -0.75, -1.0],
      repr([socket_y(m, pos, SWITCH, s) for s in ('LAN 1', 'LAN 2', 'LAN 3')]))
check('T3 alignment does not move x',
      pos['A'][0] == pos['B'][0] == pos['C'][0] != pos['SWTCH'][0])

# ── T4: alignment chains ───────────────────────────────────────────────────
job = {'devices': [
    SWITCH,
    spk('A', {'device': 'SWTCH', 'socket': 'LAN 2', 'my_socket': 'LAN_IN 1'}),
    spk('B', {'device': 'A', 'socket': 'LAN_THRU 1', 'my_socket': 'LAN_IN 1'}),
], 'circuits': []}
pos, notes = m.resolve_job_positions(job, GX, GY)
a = [d for d in job['devices'] if d['name'] == 'A'][0]
b = [d for d in job['devices'] if d['name'] == 'B'][0]
check('T4 chain resolves', notes == [], repr(notes))
check('T4 B follows A through the chain',
      abs(socket_y(m, pos, a, 'LAN_THRU 1')
          - socket_y(m, pos, b, 'LAN_IN 1')) < 1e-9)
check('T4 A still follows the switch',
      abs(socket_y(m, pos, SWITCH, 'LAN 2')
          - socket_y(m, pos, a, 'LAN_IN 1')) < 1e-9)

# ── T5: a cycle is reported, not spun on ───────────────────────────────────
job = {'devices': [
    spk('A', {'device': 'B', 'socket': 'LAN_THRU 1', 'my_socket': 'LAN_IN 1'}),
    spk('B', {'device': 'A', 'socket': 'LAN_THRU 1', 'my_socket': 'LAN_IN 1'}),
], 'circuits': []}
pos, notes = m.resolve_job_positions(job, GX, GY)
check('T5 cycle reported', len(notes) == 2, repr(notes))
check('T5 cycle explains itself', all('loops back' in n for n in notes),
      repr(notes))
check('T5 devices still get a position', set(pos) == {'A', 'B'})

# ── T6: bad references are reported, and the rest still resolves ───────────
job = {'devices': [
    SWITCH,
    spk('A', {'device': 'GHOST', 'socket': 'LAN 1', 'my_socket': 'LAN_IN 1'}),
    spk('B', {'device': 'SWTCH', 'socket': 'LAN 9', 'my_socket': 'LAN_IN 1'}),
    spk('C', {'device': 'SWTCH', 'socket': 'LAN 1', 'my_socket': 'LAN_IN 1'}),
], 'circuits': []}
pos, notes = m.resolve_job_positions(job, GX, GY)
check('T6 missing device named in the note',
      any('GHOST' in n for n in notes), repr(notes))
check('T6 missing socket named in the note',
      any('LAN 9' in n for n in notes), repr(notes))
check('T6 the good one still aligns',
      abs(socket_y(m, pos, SWITCH, 'LAN 1')
          - socket_y(m, pos, [d for d in job['devices']
                              if d['name'] == 'C'][0], 'LAN_IN 1')) < 1e-9)

# ── T7: the file picker ────────────────────────────────────────────────────
os.makedirs(m.BASE_FOLDER, exist_ok=True)
chosen = os.path.join(m.BASE_FOLDER, 'downloaded job.json')
with open(chosen, 'w', encoding='utf-8') as f:
    json.dump({'devices': [SWITCH], 'circuits': []}, f)

vs.file_choice = chosen
path, note = m.pick_job_file()
check('T7 picked file returned', path == chosen, repr((path, note)))

vs.file_choice = ''
path, note = m.pick_job_file()
check('T7 cancel is silent', path is None and note is None, repr((path, note)))

# Some builds wrap a lone VAR parameter in a tuple.
vs.file_choice = (True, chosen)
path, _note = m.pick_job_file()
check('T7 tuple return unwrapped', path == chosen, repr(path))

vs.file_choice = os.path.join(m.BASE_FOLDER, 'not there.json')
path, note = m.pick_job_file()
check('T7 missing file explained',
      path is None and note and 'no longer exists' in note, repr(note))

# ── T8: read_job honours the picked path, whatever it is called ────────────
job, problems = m.read_job(chosen)
check('T8 reads the picked file', job is not None and problems == [],
      repr(problems))
check('T8 names the real file when it is bad',
      m.read_job(os.path.join(m.BASE_FOLDER, 'nope.json'))[1][0]
      .endswith('nope.json.'),
      repr(m.read_job(os.path.join(m.BASE_FOLDER, 'nope.json'))[1]))

R.report_and_exit()
