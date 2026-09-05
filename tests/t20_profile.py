"""Document-profile tests.

A generated device only looks right if it matches how devices are already built
here. The profile reads that off the drawing: which make/model pairs exist, what
sockets each carries, and what shape names take.
"""
import os
import re
import sys
import types
from mockvs import Obj, Doc, build_vs

CC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cc_tools.py')
SANDBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sandbox_out')
results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def load(doc):
    vs = build_vs(doc)
    sys.modules['vs'] = vs
    src = re.sub(r'(?m)^run_cc_tools\(\)\s*$', '', open(CC).read())
    mod = types.ModuleType('m')
    exec(compile(src, CC, 'exec'), mod.__dict__)
    mod.BASE_FOLDER = SANDBOX
    return mod, vs


def sock(name, typ='OUT', signal='LAN', conn='EC-6A'):
    return Obj('Socket', {'type': typ, 'name': name, 'tag': name,
                          'signal': signal, 'connector': conn})


def device(name, make, model, sockets=(), room='DS Right', rack='FF Rack'):
    return Obj('Device', {
        'symbol': 'dev_label_generic', 'tag': name, 'name': name,
        'make': make, 'model': model, 'type': 'Generic',
        'loc_room': room, 'loc_rack': rack,
    }, children=list(sockets))


devs = [
    device('SPK 1.01 HL ARRAY', 'Meyer Sound', 'Galaxy 408',
           [sock('LAN_IN 1'), sock('LAN_OUT 1'), sock('AES 1', 'IN', 'AES')]),
    device('SPK 1.02 HL ARRAY', 'Meyer Sound', 'Galaxy 408',
           [sock('LAN_IN 1'), sock('LAN_OUT 1'), sock('AES 1', 'IN', 'AES')]),
    device('SWTCH 4.01', 'Cisco', 'C9300',
           [sock('LAN 1'), sock('LAN 2')]),
    device('<DEVICE>', '', ''),
]
m, vs = load(Doc([devs]))
handles, parents = m.walk_document(with_parents=True)
profile = m.build_document_profile(handles, parents)

check('T1 devices counted', profile['devices'] == 4, repr(profile['devices']))
check('T1 name == tag counted', profile['tag_equals_name'] == 4,
      repr(profile['tag_equals_name']))

shapes = {p['shape']: p['count'] for p in profile['name_patterns']}
check('T2 naming convention captured', 'AAA 9.99 AA AAAAA' in shapes,
      repr(list(shapes)[:4]))
check('T2 unnamed device excluded from patterns',
      not any('DEVICE' in s for s in shapes), repr(list(shapes)))

models = {'{} {}'.format(mm['make'], mm['model']): mm
          for mm in profile['device_models']}
check('T3 both models found', len(models) == 2, repr(list(models)))
check('T3 repeated model counted', models['Meyer Sound Galaxy 408']['count'] == 2)
check('T3 socket set captured',
      len(models['Meyer Sound Galaxy 408']['sockets']) == 3,
      repr(models['Meyer Sound Galaxy 408']['sockets']))
check('T3 socket detail captured',
      models['Meyer Sound Galaxy 408']['sockets'][2] ==
      {'name': 'AES 1', 'type': 'IN', 'signal': 'AES', 'connector': 'EC-6A'},
      repr(models['Meyer Sound Galaxy 408']['sockets'][2]))
check('T3 blank make/model not profiled',
      all(mm['make'] for mm in profile['device_models']),
      repr(profile['device_models']))

sigs = {s['value']: s['count'] for s in profile['signals']}
conns = {c['value']: c['count'] for c in profile['connectors']}
check('T4 signals gathered', sigs.get('LAN') == 6 and sigs.get('AES') == 2,
      repr(sigs))
check('T4 connectors gathered', conns.get('EC-6A') == 8, repr(conns))

rooms = {r['value'] for r in profile['rooms']}
check('T5 rooms gathered', rooms == {'DS Right'}, repr(rooms))

lines = m.profile_report_lines(profile)
text = '\n'.join(lines)
check('T6 report names the model', 'Meyer Sound Galaxy 408' in text)
check('T6 report shows a socket', 'LAN_IN 1' in text)
check('T6 report shows a convention', 'AAA 9.99 AA AAAAA' in text, text[:200])

check('T7 profile is JSON-serialisable',
      __import__('json').dumps(profile) is not None)

print()
passed = sum(1 for _n, ok, _d in results if ok)
for name, ok, detail in results:
    print('%-4s %-44s %s' % ('PASS' if ok else 'FAIL', name, '' if ok else detail))
print('\n%d/%d passed' % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
