"""Schematic-job tests.

The job file is the contract every route shares -- copy-paste, MCP, or a direct
API call all produce the same JSON and the same drawing step. It is written by
a language model, so validation is strict and reported all at once: a circuit
naming a device that does not exist should be a message, not a half-built
schematic.
"""
import json
import os
from harness import Doc, Obj, Results, load, dev

R = Results()
check = R.check

GOOD = {
    'devices': [
        {'name': 'SWTCH 4.01', 'make': 'Luminex', 'model': '10i-IP',
         'column': 0, 'row': 0,
         'sockets': [{'name': 'LAN 1', 'type': 'OUT', 'signal': 'LAN',
                      'connector': 'EC-6A', 'side': 'R'}]},
        {'name': 'SPK 1.01', 'make': 'Meyer Sound', 'model': 'TIGRA-L',
         'column': 1, 'row': 0,
         'sockets': [{'name': 'LAN_IN 1', 'type': 'IN', 'signal': 'LAN',
                      'connector': 'EC-6A', 'side': 'L'}]},
    ],
    'circuits': [
        {'from': {'device': 'SWTCH 4.01', 'socket': 'LAN 1'},
         'to': {'device': 'SPK 1.01', 'socket': 'LAN_IN 1'},
         'signal': 'MILAN PRI'},
    ],
}


def write_job(m, payload, raw=None):
    os.makedirs(m.BASE_FOLDER, exist_ok=True)
    with open(m.job_path(), 'w', encoding='utf-8') as f:
        f.write(raw if raw is not None else json.dumps(payload, indent=2))


m, vs = load(Doc([[dev('x')]]))

# ── T1: a good job reads cleanly ────────────────────────────────────────────
write_job(m, GOOD)
job, problems = m.read_job()
check('T1 valid job parses', job is not None and problems == [], repr(problems))
check('T1 devices preserved', len(job['devices']) == 2)

# ── T2: a fenced reply is still read ────────────────────────────────────────
# Pasted replies routinely arrive wrapped in a code fence.
write_job(m, None, raw='```json\n' + json.dumps(GOOD) + '\n```')
job, problems = m.read_job()
check('T2 code fence stripped', job is not None and problems == [], repr(problems))

# ── T3: every problem is reported at once, not one at a time ───────────────
bad = {
    'devices': [
        {'name': 'A'},
        {'name': 'A'},                       # duplicate: names are the link key
        {'model': 'no name here'},
    ],
    'circuits': [
        {'from': {'device': 'A', 'socket': 'X'},
         'to': {'device': 'NOT THERE', 'socket': 'Y'}},
        {'from': {'device': 'A', 'socket': 'X'}},
    ],
}
write_job(m, bad)
job, problems = m.read_job()
text = ' | '.join(problems)
check('T3 duplicate id reported', 'share the id' in text, text)
check('T3 nameless device reported', 'no name' in text, text)
check('T3 circuit to an unknown device reported',
      'not a device id' in text, text)
check('T3 circuit missing an end reported', 'no "to" device' in text, text)
check('T3 all four found together', len(problems) >= 4, repr(problems))

# ── T4: unusable input is refused, not half-read ───────────────────────────
write_job(m, None, raw='this is not json at all')
job, problems = m.read_job()
check('T4 bad JSON refused', job is None and 'not valid JSON' in problems[0],
      repr(problems))

write_job(m, {'circuits': []})
job, problems = m.read_job()
check('T4 a job with no devices is refused', job is None, repr(problems))

os.remove(m.job_path())
job, problems = m.read_job()
check('T4 a missing file says where it looked',
      job is None and m.JOB_FILE in problems[0], repr(problems))

# ── T5: layout comes from the grid, because layout IS wiring ───────────────
gx = gy = 0.25
first = m.job_position({'column': 0, 'row': 0}, gx, gy)
second = m.job_position({'column': 1, 'row': 0}, gx, gy)
third = m.job_position({'column': 0, 'row': 1}, gx, gy)
check('T5 column 0 sits at the origin', first == (0.0, 0.0), repr(first))
check('T5 the next column is to the right',
      second[0] == m.JOB_COLUMN_INCHES and second[1] == 0.0, repr(second))
check('T5 the next row is below', third[1] == -m.JOB_ROW_INCHES, repr(third))
check('T5 explicit coordinates win over the grid',
      m.job_position({'x': 7.5, 'y': -2.0, 'column': 9}, gx, gy) == (7.5, -2.0))
check('T5 a coarser grid spreads devices further apart',
      m.job_position({'column': 1, 'row': 0}, 0.5, 0.5)[0] == m.JOB_COLUMN_INCHES * 2)

# ── T6: socket specs carry signal and connector through ────────────────────
specs = m.job_socket_specs(GOOD['devices'][0])
check('T6 one spec per socket', len(specs) == 1, repr(specs))
check('T6 right side uses skt_R', specs[0][0] == 'skt_R' and specs[0][3] == 1,
      repr(specs))
check('T6 signal and connector carried',
      specs[0][4] == 'LAN' and specs[0][5] == 'EC-6A', repr(specs))
left = m.job_socket_specs(GOOD['devices'][1])
check('T6 left side uses skt_L', left[0][0] == 'skt_L' and left[0][3] == -1,
      repr(left))
check('T6 a nameless socket is skipped',
      m.job_socket_specs({'sockets': [{'type': 'IN'}]}) == [])

# ── T7: the prompt carries what a model needs ──────────────────────────────
m7, vs7 = load(Doc([[dev('SPK 1.01', 'SPK 1.01')]]))
handles, parents = m7.walk_document(with_parents=True)
profile = m7.build_document_profile(handles, parents)
reference = m7.build_reference(handles)
prompt = m7.build_prompt(profile, reference, [])
check('T7 states the job format', '"devices"' in prompt and '"circuits"' in prompt)
check('T7 says reply with JSON only', 'nothing else' in prompt, prompt[:200])
check('T7 warns names are the link key', 'link key' in prompt)
check('T7 includes the conventions of this drawing',
      'HOW THIS DRAWING IS BUILT' in prompt)
check('T7 leaves somewhere to describe the work', '>>>' in prompt)

catalogue = [{'symbol': 'S', 'folder': 'f', 'handle': None,
              'make': 'Meyer Sound', 'model': 'TIGRA-L', 'sockets': 4}]
with_symbols = m7.build_prompt(profile, reference, catalogue)
check('T7 available symbols are offered',
      'Meyer Sound TIGRA-L' in with_symbols, with_symbols[:400])

R.report_and_exit()
