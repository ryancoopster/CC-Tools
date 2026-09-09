"""Find and replace across ConnectCAD objects.

The dangerous part is not the text substitution — it is that a device name is a
LINK KEY. These fixtures are the shapes that break a drawing: a sentinel that
must not be renamed, a device whose equipment item has to follow it, and a
substring that should not match a longer name.
"""
import os
from harness import Doc, Obj, Results, load, dev, equip, sock, circuit, panel, pconn

R = Results()
check = R.check

DOC = Doc([[
    Obj('Device', {'name': 'SPK 1.01', 'tag': 'SPK 1.01'},
        children=[sock('LAN_IN 1'), sock('LAN_THRU 1')]),
    Obj('Device', {'name': 'SPK 1.010', 'tag': 'SPK 1.010'}),
    Obj('Device', {'name': '<DEVICE>', 'tag': '<DEVICE>'}),
    equip('SPK 1.01'),
    panel('SPK 1.01'),
    pconn('SPK 1.01', 'LAN_IN 1'),
    circuit(Label='SPK 1.01 FEED', Cable='SPK 1.01 NET', Number='W1',
            Signal='MILAN PRI', Src_Dev_Name='SPK 1.01'),
]])
m, vs = load(DOC)
ALL = {'device', 'equipment', 'socket', 'circuit'}
handles = m.walk_document()


def find(a, b, kinds=ALL, **kw):
    return m.find_replacements(handles, a, b, kinds, **kw)


# ── T1: substring vs whole string ─────────────────────────────────────────
sub = find('SPK 1.01', 'AMP 2.05')
check('T1 substring matches the longer name too',
      any(c['old'] == 'SPK 1.010' for c in sub),
      'SPK 1.010 contains SPK 1.01')
whole = find('SPK 1.01', 'AMP 2.05', whole=True)
check('T1 whole string does not',
      not any(c['old'] == 'SPK 1.010' for c in whole), repr([c['old'] for c in whole]))
check('T1 whole string still matches the exact one',
      any(c['old'] == 'SPK 1.01' for c in whole))

# ── T2: the text transformation itself ────────────────────────────────────
rep = m.replace_in_text
check('T2 substring replaces every occurrence',
      rep('A B A', 'A', 'Z', False, False) == 'Z B Z')
check('T2 whole string replaces the lot',
      rep('A B A', 'A B A', 'Z', False, True) == 'Z')
check('T2 whole string ignores a partial', rep('A B A', 'A', 'Z', False, True) is None)
check('T2 no match returns None', rep('HELLO', 'XYZ', 'Z', False, False) is None)
check('T2 an identical replacement is not a change',
      rep('HELLO', 'HELLO', 'HELLO', False, True) is None)
check('T2 case-insensitive by default', rep('Hello', 'hello', 'Bye', False, True) == 'Bye')
check('T2 case-sensitive respects case', rep('Hello', 'hello', 'Bye', True, True) is None)
check('T2 case-insensitive keeps surrounding casing',
      rep('MiXeD tail', 'mixed', 'X', False, False) == 'X tail')
check('T2 an empty needle matches nothing',
      rep('anything', '', 'Z', False, False) is None)

# ── T3: sentinels are never renamed ───────────────────────────────────────
# '<DEVICE>' is ConnectCAD's placeholder for an unnamed device. Renaming one
# turns a sentinel into a name and every blank device becomes that name.
check('T3 a sentinel is never offered',
      not any(c['old'] in m.SENTINELS for c in find('DEVICE', 'THING')),
      repr([c['old'] for c in find('DEVICE', 'THING')]))
check('T3 a replacement that blanks a field is refused',
      not any(c['new'].strip() == '' for c in find('SPK 1.01', '')),
      'blanking a link key collapses every affected object onto one empty key')

# ── T4: which fields are offered, and which are not ───────────────────────
fields = {c['field'] for c in find('SPK 1.01', 'X')}
check('T4 device name and tag offered', {'name', 'tag'} <= fields, repr(fields))
circ_fields = {c['field'] for c in find('SPK 1.01', 'X', {'circuit'})}
check('T4 circuit free text offered', {'Label', 'Cable'} <= circ_fields, repr(circ_fields))
check('T4 endpoint caches are NOT offered',
      'Src_Dev_Name' not in circ_fields,
      'caches are rewritten on reset; editing them is undone')
check('T4 signal is NOT offered',
      'Signal' not in circ_fields,
      'signal is a dropdown value; a free-text edit would be rejected')

# ── T5: kinds are honoured ────────────────────────────────────────────────
check('T5 sockets only', all(c['kind'] == 'socket'
                             for c in find('LAN', 'NET', {'socket'})))
check('T5 nothing when no kinds asked for', find('SPK', 'X', set()) == [])
check('T5 equipment rides with devices',
      'equipment' in m.REPLACE_GROUPS['devices'],
      'an equipment name IS its device name')

# ── T6: link keys are flagged, so the sync planner can find them ──────────
by_field = {(c['kind'], c['field']): c for c in find('SPK 1.01', 'AMP 2.05')}
check('T6 device name is a link key',
      by_field[('device', 'name')]['is_link_name'] is True)
check('T6 device tag is NOT a link key',
      by_field[('device', 'tag')]['is_link_name'] is False,
      'tags are labels nothing points at')
check('T6 equipment name is a link key',
      by_field[('equipment', 'name')]['is_link_name'] is True)

# ── T7: renaming a device carries its references ──────────────────────────
picked = [c for c in find('SPK 1.01', 'AMP 2.05', {'device'}, whole=True)
          if c['field'] == 'name']
edits = [m.make_edit(c['handle'], c['kind'], c['field'], c['old'], c['new'],
                     c['is_link_name']) for c in picked]
_w, parents = m.walk_document(with_parents=True)
sync, _used = m.plan_link_sync(edits, parents)
sync = m.dedupe_edits(edits, sync)
touched = {(e['kind'], e['field']) for e in sync}
check('T7 the equipment item follows', ('equipment', 'name') in touched, repr(touched))
check('T7 the panel layout follows', ('panel', 'DeviceName') in touched, repr(touched))
check('T7 the panel connector follows',
      ('panelconnector', 'ConnectedDev') in touched, repr(touched))
check('T7 every follow-on carries the new name',
      all(e['new'] == 'AMP 2.05' for e in sync), repr([e['new'] for e in sync]))

# ── T8: read-only until asked ─────────────────────────────────────────────
before = dict(m.get_fields(handles[0]))
find('SPK 1.01', 'AMP 2.05')
check('T8 planning changes nothing', dict(m.get_fields(handles[0])) == before)

# ── T9: the dialog offers what was asked for ─────────────────────────────
import inspect
opts = inspect.getsource(m.ask_find_replace)
for want in ('Selected objects only', 'Active layer', 'Whole document',
             'Device names', 'Socket names', 'Circuit labels',
             'Match the whole string', 'Update linked instances'):
    check('T9 offers %r' % want[:28], want in opts)
check('T9 linked instances default to on',
      'SetBooleanItem(dlg, fSyncChk, True)' in opts)

table = inspect.getsource(m.choose_replacements)
check('T9 the table shows type, field, before and after',
      all(h in table for h in ("'Type'", "'Field'", "'Current text'",
                               "'After replacing'")), table[:0])
check('T9 every row starts ticked', 'state = [True] * len(candidates)' in table)
check('T9 sorting is off',
      'EnableLBSorting(dlg, gLB, False)' in table,
      'sorting invalidates stored row indices and would tick the wrong rows')

body = inspect.getsource(m.tool_find_replace)
check('T9 no confirmation after the table',
      'AlertQuestion' not in body,
      'the user has already seen and approved every change')
check('T9 the launcher is not given a summary to pop up',
      body.rstrip().endswith("return 'done', None"), body[-160:])
check('T9 a report is still written', "save_text('find_replace'" in body)

# ── T10: a socket rename reaches the panel connector ─────────────────────
# Reported from a real drawing: renaming a socket left PanelConnector.
# ConnectedSkt pointing at a name that no longer existed.
def socket_case(dev_name, dev_tag, pconn_dev):
    doc = Doc([[
        Obj('Device', {'name': dev_name, 'tag': dev_tag},
            children=[sock('LAN_IN 1')]),
        pconn(pconn_dev, 'LAN_IN 1'),
    ]])
    mod, _vs = load(doc)
    hs = mod.walk_document()
    cands = [c for c in mod.find_replacements(hs, 'LAN_IN 1', 'NET_IN 1',
                                              {'socket'}, whole=True)
             if c['is_link_name']]
    eds = [mod.make_edit(c['handle'], c['kind'], c['field'], c['old'],
                         c['new'], c['is_link_name']) for c in cands]
    _w, par = mod.walk_document(with_parents=True)
    sync, _u = mod.plan_link_sync(eds, par)
    sync = mod.dedupe_edits(eds, sync)
    return mod, eds, sync


# The connector references the device by NAME.
_m, eds, sync = socket_case('SPK 1.01', 'SPK 1.01', 'SPK 1.01')
check('T10 connector matched by device name',
      any(e['field'] == 'ConnectedSkt' and e['new'] == 'NET_IN 1' for e in sync),
      repr([(e['kind'], e['field']) for e in sync]))

# The connector references the device by its TAG, which has drifted from the
# name. Keying on the name alone silently missed this.
_m, eds, sync = socket_case('SPK 1.01', 'SPK ONE', 'SPK ONE')
check('T10 connector matched by device TAG when it differs',
      any(e['field'] == 'ConnectedSkt' and e['new'] == 'NET_IN 1' for e in sync),
      'ConnectedDev can hold the tag, not the name')

# Neither matches: nothing can link it, and that must be REPORTED not hidden.
mod, eds, sync = socket_case('SPK 1.01', 'SPK 1.01', 'SOMETHING ELSE')
check('T10 an unmatchable connector is not silently rewritten',
      not any(e['field'] == 'ConnectedSkt' for e in sync), repr(sync))
stranded = mod.unsynced_socket_references(eds, sync)
check('T10 and it IS reported', stranded == [('SOMETHING ELSE', 'LAN_IN 1')],
      repr(stranded))

# A connector that was synced is not also reported as stranded.
mod, eds, sync = socket_case('SPK 1.01', 'SPK 1.01', 'SPK 1.01')
check('T10 a synced connector is not reported as stranded',
      mod.unsynced_socket_references(eds, sync) == [],
      repr(mod.unsynced_socket_references(eds, sync)))

# Socket names repeat across devices, so the device must stay part of the key.
two = Doc([[
    Obj('Device', {'name': 'SPK A', 'tag': 'SPK A'}, children=[sock('LAN_IN 1')]),
    Obj('Device', {'name': 'SPK B', 'tag': 'SPK B'}, children=[sock('LAN_IN 1')]),
    pconn('SPK B', 'LAN_IN 1'),
]])
mod, _vs = load(two)
hs = mod.walk_document()
target = [h for h in hs if mod.classify(h) == 'socket'][0]      # the one in SPK A
eds = [mod.make_edit(target, 'socket', 'name', 'LAN_IN 1', 'NET_IN 1', True)]
_w, par = mod.walk_document(with_parents=True)
sync, _u = mod.plan_link_sync(eds, par)
check('T10 a connector on a DIFFERENT device is left alone',
      not any(e['field'] == 'ConnectedSkt' for e in sync),
      'SPK B/LAN_IN 1 is a different socket that happens to share a name')

# ── T11: the field a real drawing actually uses ──────────────────────────
# From ART Schematics.vwx: panel connectors carried the socket name in
# SocketName and DisplayTag, with ConnectedSkt empty. Syncing only
# ConnectedSkt left every one of them pointing at a name that no longer
# existed, and said nothing.
def own_pconn(socket_name, tag=None, connected_dev='', connected_skt=''):
    return Obj('PanelConnector', {
        'SocketName': socket_name,
        'DisplayTag': socket_name if tag is None else tag,
        'ConnectedDev': connected_dev, 'ConnectedSkt': connected_skt})


def rename_socket(objects, old='ISL - 25', new='TRUNK - 25'):
    mod, _vs = load(Doc([objects]))
    hs = mod.walk_document()
    target = [h for h in hs if mod.classify(h) == 'socket'
              and mod.read_field(h, 'name') == old]
    eds = [mod.make_edit(h, 'socket', 'name', old, new, True) for h in target]
    _w, par = mod.walk_document(with_parents=True)
    sync, _u = mod.plan_link_sync(eds, par)
    return mod, eds, mod.dedupe_edits(eds, sync)


# The real shape: connector knows only its own SocketName.
mod, eds, sync = rename_socket([
    Obj('Device', {'name': 'CTP_WEST PB RACK', 'tag': 'CTP_WEST PB RACK'},
        children=[sock('ISL - 25')]),
    own_pconn('ISL - 25'),
])
fields = {(e['field'], e['new']) for e in sync}
check('T11 SocketName follows the rename',
      ('SocketName', 'TRUNK - 25') in fields, repr(fields))
check('T11 DisplayTag follows when it showed the socket name',
      ('DisplayTag', 'TRUNK - 25') in fields, repr(fields))

# A customised label is the user's and must not be overwritten.
mod, eds, sync = rename_socket([
    Obj('Device', {'name': 'CTP_WEST PB RACK', 'tag': 'CTP_WEST PB RACK'},
        children=[sock('ISL - 25')]),
    own_pconn('ISL - 25', tag='WEST TRUNK A'),
])
fields = {(e['field'], e['new']) for e in sync}
check('T11 SocketName still follows', ('SocketName', 'TRUNK - 25') in fields)
check('T11 a customised DisplayTag is left alone',
      not any(f == 'DisplayTag' for f, _v in fields), repr(fields))

# Two devices, same socket name, both renamed the same way: unambiguous.
mod, eds, sync = rename_socket([
    Obj('Device', {'name': 'CTP_WEST PB RACK', 'tag': 'CTP_WEST PB RACK'},
        children=[sock('ISL - 25')]),
    Obj('Device', {'name': 'CTP_EAST PB RACK', 'tag': 'CTP_EAST PB RACK'},
        children=[sock('ISL - 25')]),
    own_pconn('ISL - 25'),
])
check('T11 an unambiguous rename reaches an unscoped connector',
      any(e['field'] == 'SocketName' for e in sync), repr(sync))

# Renamed two different ways: ambiguous, so the bare name is NOT followed.
mod2, _vs = load(Doc([[
    Obj('Device', {'name': 'A', 'tag': 'A'}, children=[sock('ISL - 25')]),
    Obj('Device', {'name': 'B', 'tag': 'B'}, children=[sock('ISL - 25')]),
    own_pconn('ISL - 25'),
]]))
hs = mod2.walk_document()
socks = [h for h in hs if mod2.classify(h) == 'socket']
eds = [mod2.make_edit(socks[0], 'socket', 'name', 'ISL - 25', 'TRUNK - 25', True),
       mod2.make_edit(socks[1], 'socket', 'name', 'ISL - 25', 'SPUR - 25', True)]
_w, par = mod2.walk_document(with_parents=True)
sync, _u = mod2.plan_link_sync(eds, par)
check('T11 an ambiguous rename is not guessed at',
      not any(e['field'] == 'SocketName' for e in sync),
      'two answers for one name means no safe answer')
check('T11 unambiguous_socket_map drops the ambiguous one',
      mod2.unambiguous_socket_map(eds) == {}, repr(mod2.unambiguous_socket_map(eds)))

# Scoping still works when the connector sits inside a panel layout.
mod, eds, sync = rename_socket([
    Obj('Device', {'name': 'CTP_WEST PB RACK', 'tag': 'CTP_WEST PB RACK'},
        children=[sock('ISL - 25')]),
    Obj('PanelLayout', {'DeviceType': 'CustomPanel',
                        'DeviceName': 'CTP_WEST PB RACK'},
        children=[own_pconn('ISL - 25')]),
])
check('T11 a connector nested in a panel layout is scoped by its device',
      any(e['field'] == 'SocketName' and e['new'] == 'TRUNK - 25' for e in sync),
      repr([(e['field'], e['new']) for e in sync]))

# ConnectedSkt, where a drawing does use it, still works.
mod, eds, sync = rename_socket([
    Obj('Device', {'name': 'DEV', 'tag': 'DEV'}, children=[sock('ISL - 25')]),
    Obj('PanelConnector', {'SocketName': '', 'DisplayTag': 'P',
                           'ConnectedDev': 'DEV', 'ConnectedSkt': 'ISL - 25'}),
])
check('T11 ConnectedSkt is still synced',
      any(e['field'] == 'ConnectedSkt' and e['new'] == 'TRUNK - 25' for e in sync),
      repr([(e['field'], e['new']) for e in sync]))

R.report_and_exit()
