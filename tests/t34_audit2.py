"""The rest of the audit findings.

Mostly cases where the plug-in was right about the common shape and wrong about
a second one: a reference that lives in two fields, a record that is not a
device but is not nothing, an enum collapsed to a boolean.
"""
import inspect
from harness import Doc, Obj, Results, load, dev, equip, sock, circuit

R = Results()
check = R.check
m, vs = load(Doc([[dev('x')]]))

# ── T1: Device-External is reachable, its sentinel still is not ──────────
EXT = Obj('Device-External', {'name': '<EXT>', 'tag': 'To SWTCH 2.01 2nd Floor',
                              'description': ''})
mod, _vs = load(Doc([[EXT]]))
hs = mod.walk_document()
check('T1 it now has a kind', mod.classify(hs[0]) == 'external',
      repr(mod.classify(hs[0])))
found = mod.find_replacements(hs, 'SWTCH', 'SWITCH', {'external'})
check('T1 its tag is findable', any(c['old'].startswith('To SWTCH')
                                    for c in found), repr(found))
check('T1 the <EXT> sentinel is never offered',
      not any(c['old'] == '<EXT>' for c in found),
      'name really is a placeholder and renaming it would be corruption')
check('T1 nothing it offers is a link key',
      all(not c['is_link_name'] for c in found), repr(found))
check('T1 Search covers it', 'external' in mod.REPLACE_GROUPS['devices'])
check('T1 Spell Check covers it', 'external' in mod.SPELL_FIELDS)
check('T1 it is labelled by its tag',
      mod.object_label(hs[0], 'external') == 'To SWTCH 2.01 2nd Floor',
      repr(mod.object_label(hs[0], 'external')))

# ── T2: a device TAG is a reference target ──────────────────────────────
mod, _vs = load(Doc([[
    Obj('Device', {'name': 'SPK 1', 'tag': 'OLD TAG'}),
    Obj('PanelConnector', {'SocketName': '', 'DisplayTag': 'P',
                           'ConnectedDev': 'OLD TAG', 'ConnectedSkt': ''}),
    Obj('PanelLayout', {'DeviceType': 'CustomPanel', 'DeviceName': 'OLD TAG'}),
]]))
hs = mod.walk_document()
device = [h for h in hs if mod.classify(h) == 'device'][0]
eds = [mod.make_edit(device, 'device', 'tag', 'OLD TAG', 'NEW TAG', False)]
_w, par = mod.walk_document(with_parents=True)
sync, _u = mod.plan_link_sync(eds, par)
fields = {(e['kind'], e['field'], e['new']) for e in sync}
check('T2 a connector holding the tag follows',
      ('panelconnector', 'ConnectedDev', 'NEW TAG') in fields, repr(fields))
check('T2 a panel layout holding the tag follows',
      ('panel', 'DeviceName', 'NEW TAG') in fields, repr(fields))

# A value that is a live device NAME must not be read as somebody's tag.
mod2, _vs = load(Doc([[
    Obj('Device', {'name': 'SPK 1', 'tag': 'SPK 2'}),
    Obj('Device', {'name': 'SPK 2', 'tag': 'SPK 2'}),
    Obj('PanelConnector', {'SocketName': '', 'DisplayTag': 'P',
                           'ConnectedDev': 'SPK 2', 'ConnectedSkt': ''}),
]]))
hs2 = mod2.walk_document()
first = [h for h in hs2 if mod2.classify(h) == 'device'][0]
eds2 = [mod2.make_edit(first, 'device', 'tag', 'SPK 2', 'RENAMED', False)]
_w, par2 = mod2.walk_document(with_parents=True)
sync2, _u = mod2.plan_link_sync(eds2, par2)
check('T2 a tag that is another device name is left alone',
      not any(e['field'] == 'ConnectedDev' for e in sync2),
      'ConnectedDev "SPK 2" means the device NAMED that')

# ── T3: half-rack is reachable ──────────────────────────────────────────
def width_for(text):
    entry = m.parse_golden_devices(
        '## A | B\n\n- Rack mounted: %s\n\n| Socket | Type |\n|---|---|\n| X | IN |\n'
        % text)[(m.normalise_model('A'), m.normalise_model('B'))]
    return m.golden_rack_width(entry)


for text, want in (('half-rack', 'half-rack'), ('half', 'half-rack'),
                   ('yes', 'full-rack'), ('full-rack', 'full-rack'),
                   ('no', 'non-rack'), ('non-rack', 'non-rack')):
    check('T3 %-10r -> %s' % (text, want), width_for(text) == want,
          repr(width_for(text)))

entry = m.parse_golden_devices(
    '## A | B\n\n- Rack mounted: half-rack\n\n| Socket | Type |\n|---|---|\n| X | IN |\n'
)[(m.normalise_model('A'), m.normalise_model('B'))]
phys = m.golden_physical(entry)
check('T3 it survives into the physical dict', phys.get('rack_width') == 'half-rack',
      repr(phys))
d = Obj('Device', {'width': '', 'height': '', 'depth': '', 'weight': '',
                   'power': '', 'width_R': '', 'heightU': ''})
m.apply_physical_properties(d, phys, 1.0)
check('T3 and is written to the device', d.fields['width_R'] == 'half-rack',
      repr(d.fields['width_R']))

# The shipped database only knows 19-inch panels, so it still says full-rack.
row = [''] * 20
row[2], row[3] = '482.6', '44.45'
d2 = Obj('Device', {'width': '', 'height': '', 'depth': '', 'weight': '',
                    'power': '', 'width_R': '', 'heightU': ''})
m.apply_physical_properties(d2, m.db_physical({'rows': [row]}), 1.0)
check('T3 the database path still works', d2.fields['width_R'] == 'full-rack',
      repr(d2.fields['width_R']))

# ── T4: the reference scan looks for tags and socket names too ──────────
buckets = {'Device': [], 'Socket': []}
mod, _vs = load(Doc([[
    Obj('Device', {'name': 'DEV A', 'tag': 'TAG A'},
        children=[sock('SKT A')]),
]]))
hs = mod.walk_document()
buckets = mod.group_by_record(hs)
keys = mod.collect_reference_keys(buckets)
check('T4 device names collected', keys['device name'] == {'DEV A'}, repr(keys))
check('T4 device tags collected too', keys['device tag'] == {'TAG A'}, repr(keys))
check('T4 socket names collected too', 'SKT A' in keys['socket name'], repr(keys))
check('T4 the old entry point still works',
      mod.collect_device_names(buckets) == {'DEV A'})

hits = mod.scan_name_references(buckets, keys)
kinds = set()
for entry in hits.values():
    kinds.update(entry['kinds'])
check('T4 hits record what kind of string matched',
      {'device name', 'device tag', 'socket name'} <= kinds, repr(kinds))
check('T4 a plain set is still accepted',
      mod.scan_name_references(buckets, {'DEV A'}) != {},
      'the old two-argument shape must keep working')

# ── T5: the fallback warning reaches every renaming tool ────────────────
for builder in ('write_normalise_report', 'write_match_report',
                'write_spelling_report'):
    body = inspect.getsource(getattr(m, builder))
    check('T5 %s carries the warning' % builder,
          'fallback_rename_note' in body, builder)
check('T5 Find and Replace does too',
      'fallback_rename_note' in inspect.getsource(m.tool_find_replace))

# ── T6: wire_job cannot touch a circuit it did not create ───────────────
wire = inspect.getsource(m.wire_job)
check('T6 pre-existing circuits are snapshotted', 'pre_existing' in wire)
check('T6 before ConnectSelected runs',
      wire.index('pre_existing = ') < wire.index("command('ConnectSelected'"),
      'snapshotting afterwards would capture the ones just made')
check('T6 and excluded from the match',
      'if handle in pre_existing' in wire, wire[:0])
check('T6 an unreadable state is not read as unwired',
      'CC_GetCircuitSource unavailable' in wire,
      'blaming the circuits for a missing routine reports real wiring as failed')

# ── T7: a socket only counts once placed and named ──────────────────────
probe = inspect.getsource(m.probe_make_device)
check('T7 placement result is checked',
      'if not place_socket(' in probe, probe[:0])
check('T7 field writes are checked',
      probe.count('problems.append') >= 4, repr(probe.count('problems.append')))
check('T7 a failure is not counted as added',
      'failed_sockets += 1' in probe and 'continue' in probe)
check('T7 socket fields are resolved, not hard-coded',
      'SOCKET_NAME_FIELDS' in probe and 'SOCKET_TAG_FIELDS' in probe)

R.report_and_exit()
