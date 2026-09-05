"""Shared scaffolding for the CC Tools suites.

Loads cc_tools.py against the mock `vs` module with report output redirected
into a sandbox, so a test run can never write into the user's real
~/Documents/CC Tools folder. It did once; hence this.
"""
import os
import re
import sys
import types

from mockvs import Obj, Doc, build_vs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CC = os.path.join(ROOT, 'cc_tools.py')
SANDBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sandbox_out')


def load(doc, associations=None, selected=()):
    """Exec cc_tools.py with a fake vs module. Returns (module, vs).

    `associations` stands in for ConnectCAD's stored device<->equipment link;
    pass None to simulate the routine being absent (no ConnectCAD licence)."""
    vs = build_vs(doc, selected=selected)
    if associations is not None:
        vs.CC_GetEquipmentItem = lambda h: associations.get(h)
    sys.modules['vs'] = vs
    src = re.sub(r'(?m)^run_cc_tools\(\)\s*$', '', open(CC).read())
    mod = types.ModuleType('cc_tools')
    exec(compile(src, CC, 'exec'), mod.__dict__)
    mod.BASE_FOLDER = SANDBOX
    return mod, vs


# ─── Object builders ─────────────────────────────────────────────────────────
def dev(name, tag=None, **extra):
    fields = {'name': name, 'tag': tag if tag is not None else name}
    fields.update(extra)
    return Obj('Device', fields)


def full_dev(name, make='Meyer Sound', model='Galaxy 408', sockets=()):
    """A device carrying the library and dropdown fields a real one has."""
    return Obj('Device', {
        'name': name, 'tag': name,
        'description': 'Meyer Sound_2100-LFC',
        'make': make, 'model': model, 'type': 'Generic',
        'loc_room': 'DS Right', 'loc_rack': 'FF Rack',
        'user1': '', 'user2': '',
    }, children=list(sockets))


def equip(name, **extra):
    fields = {'name': name}
    fields.update(extra)
    return Obj('EquipItem', fields)


def sock(name, typ='OUT', signal='LAN', conn='EC-6A'):
    return Obj('Socket', {'type': typ, 'name': name, 'tag': name,
                          'signal': signal, 'connector': conn, 'user1': ''})


def pconn(devname, sktname=''):
    return Obj('PanelConnector', {'SocketName': '', 'DisplayTag': 'P',
                                  'ConnectedDev': devname,
                                  'ConnectedSkt': sktname})


def panel(devname):
    return Obj('PanelLayout', {'DeviceType': 'CustomPanel',
                               'DeviceName': devname})


def circuit(**fields):
    base = {'Label': '', 'Number': '', 'Cable': '', 'Signal': 'AVB Pri',
            'Src_Dev_Name': '', 'Dst_Dev_Name': ''}
    base.update(fields)
    return Obj('Circuit', base)


# ─── Result collection ───────────────────────────────────────────────────────
class Results:
    def __init__(self):
        self.rows = []

    def check(self, name, cond, detail=''):
        self.rows.append((name, bool(cond), detail))

    def report_and_exit(self):
        print()
        passed = sum(1 for _n, ok, _d in self.rows if ok)
        for name, ok, detail in self.rows:
            print('%-4s %-52s %s' % ('PASS' if ok else 'FAIL', name,
                                     '' if ok else detail))
        print('\n%d/%d passed' % (passed, len(self.rows)))
        sys.exit(0 if passed == len(self.rows) else 1)
