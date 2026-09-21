"""Reconciling panel connectors after a socket is renamed outside CC Tools.

ConnectCAD does not push a schematic socket rename out to the panel connectors
pointing at it, and nothing in the VectorScript API can watch for one as it
happens. So this works by snapshot and diff, using the persistent uuid every
plug-in object carries.
"""
import os
import tempfile
from harness import Doc, Obj, Results, load, dev, sock

R = Results()
check = R.check


def build(socket_name='ISL - 25', connected='ISL - 25', own='ISL - 25'):
    doc = Doc([[
        Obj('Device', {'name': 'CTP WEST', 'tag': 'CTP WEST'},
            children=[sock(socket_name)]),
        Obj('PanelConnector', {'SocketName': own, 'DisplayTag': own,
                               'ConnectedDev': 'CTP WEST',
                               'ConnectedSkt': connected}),
    ]])
    mod, vsm = load(doc)
    mod.BASE_FOLDER = tempfile.mkdtemp()
    return mod, vsm


# ── T1: a uuid is stable, and identifies a socket across a rename ────────
m, vs = build()
hs = m.walk_document()
socket = [h for h in hs if m.classify(h) == 'socket'][0]
first = m.object_uuid(socket)
check('T1 a socket has a uuid', bool(first), repr(first))
check('T1 it is stable across reads', m.object_uuid(socket) == first)
m.write_field(socket, 'name', 'TRUNK - 25')
check('T1 and survives a rename', m.object_uuid(socket) == first,
      'identity is the whole basis of the diff')

# ── T2: the first run has nothing to compare against ─────────────────────
m, vs = build()
check('T2 no snapshot to begin with', m.load_socket_snapshot() == {})
status, _s = m.tool_reconcile_panels()
check('T2 it records one instead of guessing', status == 'done')
snap = m.load_socket_snapshot()
check('T2 the snapshot has the socket', len(snap) == 1, repr(snap))
check('T2 with its current name',
      list(snap.values())[0]['name'] == 'ISL - 25', repr(snap))
check('T2 and its owning device',
      list(snap.values())[0]['device'] == 'CTP WEST', repr(snap))

# ── T3: a rename is detected by uuid, not by guesswork ───────────────────
hs = m.walk_document()
socket = [h for h in hs if m.classify(h) == 'socket'][0]
m.write_field(socket, 'name', 'TRUNK - 25')
m.write_field(socket, 'tag', 'TRUNK - 25')
hs, parents = m.walk_document(with_parents=True)
renames = m.find_socket_renames(hs, parents, m.load_socket_snapshot())
check('T3 one rename found', len(renames) == 1, repr(renames))
check('T3 with the old and new names',
      renames[0]['old'] == 'ISL - 25' and renames[0]['new'] == 'TRUNK - 25',
      repr(renames[0]))

# ── T4: the panel connector is brought up to date ────────────────────────
stand_ins = [m.make_edit(r['handle'], 'socket', r['field'], r['old'], r['new'],
                         True) for r in renames]
sync, _u = m.plan_link_sync(stand_ins, parents)
sync = m.dedupe_edits(stand_ins, sync)
fields = {(e['field'], e['new']) for e in sync}
check('T4 ConnectedSkt follows', ('ConnectedSkt', 'TRUNK - 25') in fields,
      repr(fields))
check('T4 SocketName follows', ('SocketName', 'TRUNK - 25') in fields,
      repr(fields))
check('T4 the socket itself is not rewritten',
      not any(e['kind'] == 'socket' for e in sync),
      'it was already renamed; these stand in so the planner can work')

# ── T5: an unchanged drawing produces nothing ────────────────────────────
m2, _vs = build()
m2.tool_reconcile_panels()                      # takes the first snapshot
hs2, par2 = m2.walk_document(with_parents=True)
check('T5 no rename, no work',
      m2.find_socket_renames(hs2, par2, m2.load_socket_snapshot()) == [])

# ── T6: a deleted socket is not mistaken for a rename ────────────────────
snapshot = dict(m2.load_socket_snapshot())
snapshot['uuid-that-no-longer-exists'] = {'name': 'GONE', 'device': 'X'}
check('T6 a vanished uuid is ignored',
      m2.find_socket_renames(hs2, par2, snapshot) == [],
      'a socket that was deleted has nothing to carry forward')

# ── T7: snapshots are per document ───────────────────────────────────────
m3, vs3 = build()
m3.save_socket_snapshot({'uuid-a': {'name': 'A', 'device': 'D'}})
vs3.file_name = 'OTHER.vwx'
check('T7 another drawing sees its own (empty) history',
      m3.load_socket_snapshot() == {},
      'two drawings must not read each other as a pile of renames')

# ── T8: background watching is not claimed ───────────────────────────────
import inspect
srcfile = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'cc_tools.py'), encoding='utf-8').read()
check('T8 the limitation is written down, not glossed',
      'no timer, no idle' in srcfile.replace('\n# ', ' ').replace('\n', ' ')
      or 'There is no timer' in srcfile,
      'a feature that cannot exist should say so where someone will read it')

# ── T9: an unrelated CC Tools run must not erase a pending rename ────────
# The snapshot refreshes at the end of EVERY run. Advancing it on a socket
# whose name has drifted would destroy the only record that a rename happened,
# leaving the panel connector stale with no way left to find it.
m, vs = build()
m.tool_reconcile_panels()                       # first snapshot
skt = [h for h in m.walk_document() if m.classify(h) == 'socket'][0]
m.write_field(skt, 'name', 'TRUNK - 25')
m.write_field(skt, 'tag', 'TRUNK - 25')

for _ in range(3):
    m.save_socket_snapshot()                    # three unrelated runs
hs, par = m.walk_document(with_parents=True)
renames = m.find_socket_renames(hs, par, m.load_socket_snapshot())
check('T9 the rename survives unrelated runs', len(renames) == 1, repr(renames))
check('T9 the snapshot still holds the OLD name',
      any(v['name'] == 'ISL - 25' for v in m.load_socket_snapshot().values()),
      repr(m.load_socket_snapshot()))
check('T9 and it is counted as pending', m.save_socket_snapshot.pending == 1,
      repr(m.save_socket_snapshot.pending))

# New sockets must still be recorded while a rename is pending.
device = [h for h in hs if m.classify(h) == 'device'][0]
device.children.append(Obj('Socket', {'type': 'IN', 'name': 'NEW 1',
                                      'tag': 'NEW 1', 'signal': 'LAN',
                                      'connector': 'EC-6A', 'user1': ''}))
m.save_socket_snapshot()
snap = m.load_socket_snapshot()
check('T9 a new socket is still added', any(v['name'] == 'NEW 1'
                                            for v in snap.values()), repr(snap))
check('T9 without disturbing the pending rename',
      any(v['name'] == 'ISL - 25' for v in snap.values()), repr(snap))

# ── T10: settling advances the record, and only for what settled ─────────
uuid = m.object_uuid(skt)
m.save_socket_snapshot(settled=[uuid])
check('T10 a settled rename advances',
      any(v['name'] == 'TRUNK - 25' for v in m.load_socket_snapshot().values()),
      repr(m.load_socket_snapshot()))
hs, par = m.walk_document(with_parents=True)
check('T10 and stops being reported',
      m.find_socket_renames(hs, par, m.load_socket_snapshot()) == [])

# A rename with a reference left behind must stay on the books.
m2, _vs = build()
m2.tool_reconcile_panels()
s2 = [h for h in m2.walk_document() if m2.classify(h) == 'socket'][0]
m2.write_field(s2, 'name', 'TRUNK - 25')
m2.save_socket_snapshot(settled=[])             # nothing settled
hs2, par2 = m2.walk_document(with_parents=True)
check('T10 an unsettled rename stays visible',
      len(m2.find_socket_renames(hs2, par2, m2.load_socket_snapshot())) == 1,
      'one unticked reference keeps the whole rename outstanding')

R.report_and_exit()
