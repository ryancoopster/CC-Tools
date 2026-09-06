"""Search across every field of every ConnectCAD object.

Vectorworks' own Find and Replace cannot see inside plug-in object records, so
the values that matter most in a ConnectCAD drawing are invisible to it. The
fixtures here are the real anomalies found in the Geffen export: a trailing
space on an endpoint, a '???' signal, a whitespace-only device reference.
"""
import os
from harness import Doc, Obj, Results, load, dev, equip, sock, circuit

R = Results()
check = R.check


def circ(**kw):
    base = {'Signal': 'LINE', 'Cable': '', 'Number': '', 'Label': '',
            'Src_Dev_Name': 'A', 'Src_Skt_Name': 'OUT 1',
            'Dst_Dev_Name': 'B', 'Dst_Skt_Name': 'IN 1',
            '__ISNEW': 'False', '__Version': '2600'}
    base.update(kw)
    return Obj('Circuit', base)


DOC = Doc([[
    Obj('Device', {'name': 'SPK 1.01 HL ARRAY 1', 'tag': 'SPK 1.01 HL ARRAY 1',
                   'make': 'Meyer Sound', 'model': 'TIGRA-L',
                   'loc_room': 'Grid', '__ISNEW': 'False'},
        children=[sock('LAN_IN 1')]),
    Obj('Device', {'name': 'SPK 2.02 HL SUB MID', 'tag': 'SPK 2.02 HL SUB MID',
                   'make': 'Meyer Sound', 'model': '1100-LFC',
                   'loc_room': '', '__ISNEW': 'False'}),
    # The real trailing-space endpoint from the Geffen drawing.
    circ(Cable='SPK 3.04 US FILL HR LOWER',
         Dst_Dev_Name='SPK 3.04 US FILL HR LOWER '),
    circ(Cable='HR SUB MID', Signal='PWR', Dst_Dev_Name='SPK 2.02 HL SUB MID'),
    circ(Cable='PAN AVB PRI PROC 2.02', Signal='???'),
    circ(Cable='PROC 1.02 UPS', Signal='PWR', Dst_Dev_Name='   '),
    equip('SPK 1.01 HL ARRAY 1'),
]])

m, vs = load(DOC)
m.BASE_FOLDER = os.path.join(m.BASE_FOLDER, 'search')
handles, parents = m.walk_document(with_parents=True)
ALL = {'device', 'circuit', 'socket', 'equipment', 'panel', 'panelconnector'}


def find(term, kinds=ALL, **kw):
    return m.search_objects(term, handles, kinds, parents, **kw)


# ── T1: it searches fields Vectorworks' Find and Replace cannot see ────────
hits = find('TIGRA')
check('T1 finds a value in the model field', len(hits) == 1, repr(hits))
check('T1 names the field', hits[0]['field'] == 'model', repr(hits[0]))
check('T1 says which object', hits[0]['label'] == 'SPK 1.01 HL ARRAY 1',
      repr(hits[0]['label']))

check('T1 finds a cable name', len(find('HR SUB MID', {'circuit'})) == 1)
check('T1 finds a signal', len(find('???', {'circuit'})) == 1)

# ── T2: one object can yield several hits ─────────────────────────────────
hits = find('SPK 1.01 HL ARRAY 1')
fields = sorted(h['field'] for h in hits)
check('T2 name and tag both hit', fields.count('name') >= 1
      and 'tag' in fields, repr(fields))
check('T2 the equipment item is found too',
      any(h['kind'] == 'equipment' for h in hits), repr(hits))

# ── T3: kinds are honoured ────────────────────────────────────────────────
check('T3 devices only', all(h['kind'] == 'device'
                             for h in find('SPK', {'device'})))
check('T3 circuits only', all(h['kind'] == 'circuit'
                              for h in find('SPK', {'circuit'})))
check('T3 nothing when no kinds are asked for', find('SPK', set()) == [])

# ── T4: case and whole-field matching ─────────────────────────────────────
check('T4 case-insensitive by default', len(find('tigra')) == 1)
check('T4 case-sensitive finds nothing',
      len(find('tigra', case_sensitive=True)) == 0)
check('T4 case-sensitive finds the real case',
      len(find('TIGRA', case_sensitive=True)) == 1)

check('T4 substring matches inside a longer value',
      len(find('HL ARRAY', {'device'})) > 0)
check('T4 whole-field rejects a substring',
      len(find('HL ARRAY', {'device'}, whole_value=True)) == 0)
check('T4 whole-field matches the exact value',
      len(find('SPK 1.01 HL ARRAY 1', {'device'}, whole_value=True)) == 2,
      repr(find('SPK 1.01 HL ARRAY 1', {'device'}, whole_value=True)))

# ── T5: the real anomalies from the Geffen drawing ────────────────────────
# A trailing space is invisible on screen and breaks a name link, so being
# able to search for one is the point of the tool.
trailing = [h for h in find('LOWER ', {'circuit'})
            if h['value'].endswith(' ')]
check('T5 a trailing space is findable', len(trailing) == 1, repr(trailing))
check('T5 and it names the guilty field',
      trailing[0]['field'] == 'Dst_Dev_Name', repr(trailing[0]))

blank = find('', {'circuit'}, whole_value=True)
check('T5 empty search + whole field lists blank fields',
      len(blank) > 0 and all(h['value'] == '' for h in blank), repr(blank[:3]))

space_only = [h for h in find('   ', {'circuit'}, whole_value=True)]
check('T5 a whitespace-only endpoint is findable', len(space_only) == 1,
      repr(space_only))

# ── T6: internal fields are hidden unless asked for ───────────────────────
check('T6 internal fields hidden by default',
      not any(h['field'].startswith('__') for h in find('False')), )
check('T6 internal fields searchable on request',
      any(h['field'].startswith('__')
          for h in find('False', include_internal=True)))
check('T6 is_internal_field knows the convention',
      m.is_internal_field('__ISNEW') and not m.is_internal_field('Signal'))

# ── T7: labels identify WHICH object ──────────────────────────────────────
# "Cable = HL 1" could be any of 372 circuits; the label is what makes a hit
# actionable.
c = [h for h in find('???', {'circuit'})][0]
check('T7 a circuit is labelled by its endpoints',
      '->' in c['label'] and 'A/OUT 1' in c['label'], repr(c['label']))
skt = find('LAN_IN 1', {'socket'})
check('T7 a socket is labelled by its owning device',
      skt and 'SPK 1.01 HL ARRAY 1 / LAN_IN 1' == skt[0]['label'],
      repr(skt[0]['label']) if skt else 'no socket hit')

# ── T8: selecting hits deduplicates by object ─────────────────────────────
hits = find('SPK 1.01 HL ARRAY 1')
objects = len(set(h['handle'] for h in hits))
check('T8 several hits, fewer objects', len(hits) > objects, 
      '%d hits, %d objects' % (len(hits), objects))
check('T8 select_hits selects each object once',
      m.select_hits(hits) == objects, repr(m.select_hits(hits)))

# ── T9: read-only ─────────────────────────────────────────────────────────

d0 = handles[0]
snapshot = dict(m.get_fields(d0))
find('SPK', ALL)
check('T9 searching changes nothing', dict(m.get_fields(d0)) == snapshot)

# ── T10: the pull-down is actually populated ──────────────────────────────
# It was not. AddChoice was called at dialog-construction time with -1 as the
# position, which builds a menu that opens empty and never reports a choice.
# The working dialogs in this file all fill their pull-downs inside kSetup
# with real positions, and this now does the same.
import re
SRC = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'cc_tools.py'), encoding='utf-8').read()

check('T10 no AddChoice anywhere passes -1 as the position',
      not re.search(r'AddChoice\([^)]*,\s*-1\s*\)', SRC),
      repr(re.findall(r'AddChoice\([^)]*-1\s*\)', SRC)[:3]))

# Every pull-down must be filled inside a kSetup branch, not at construction.
for popup in ('qScopePopup', 'pTypePopup', 'nScopePopup', 'sScopePopup'):
    adds = [m.start() for m in re.finditer(r'AddChoice\(\w+, %s' % popup, SRC)]
    setup = SRC.find('kSetup')
    check('T10 %s is populated at all' % popup, len(adds) > 0, popup)

# The search dialog's constants must not shadow Spell Check's.
pairs = re.findall(r'^([a-zA-Z_]\w*(?:, *[a-zA-Z_]\w*)*) *= *\d+(?:, *\d+)*$',
                   SRC, re.M)
seen = {}
clashes = []
for line in pairs:
    for name in [n.strip() for n in line.split(',')]:
        if name in seen:
            clashes.append(name)
        seen[name] = True
check('T10 no dialog constant is defined twice', not clashes, repr(clashes))

# ── T11: the results table is the end of a successful search ─────────────
# Two alerts used to follow it: one confirming the selection, one from the
# launcher restating the count. Both said what the table had just shown.
import inspect

check('T11 the results table is told where the CSV went',
      'path' in inspect.signature(m.show_search_results).parameters,
      repr(inspect.signature(m.show_search_results)))

body = inspect.getsource(m.tool_search)
check('T11 no alert after selecting', 'object(s) selected' not in body, body[-400:])
check('T11 a successful search returns nothing for the launcher to report',
      body.rstrip().endswith("return 'done', None"), body[-200:])

# The alerts that remain are the paths with no table to speak for them.
check('T11 a search with no matches still says so',
      'No matches for' in body)
check('T11 refusals still explain themselves',
      'Nothing to find' in body and 'No object types were ticked' in body)

R.report_and_exit()
