"""A fake `vs` module: enough of the Vectorworks API to execute cc_tools.py
against a synthetic ConnectCAD document, so the logic can be tested without
Vectorworks running.

Lives in the repo rather than a scratch directory because the suite is the only
thing standing between a refactor and a silently corrupted drawing.
"""
import types

TYPE_PIO = 86
TYPE_GROUP = 11
TYPE_OTHER = 2


class Obj:
    """One fake plug-in object. `fields` is an ordered dict of field -> value."""
    _next = [1]

    def __init__(self, record, fields, children=None):
        self.id = Obj._next[0]
        Obj._next[0] += 1
        self.record = record
        self.fields = dict(fields)
        self.order = list(fields.keys())
        self.children = children or []

    def __repr__(self):
        return '<%s #%d %r>' % (self.record, self.id, self.fields)


class Doc:
    def __init__(self, layers):
        self.layers = layers                 # list of list-of-Obj
        self._next = {}
        for objs in layers:
            for i, o in enumerate(objs):
                self._next[id(o)] = objs[i + 1] if i + 1 < len(objs) else None
                self._index(o)

    def _index(self, parent):
        kids = parent.children
        for i, k in enumerate(kids):
            self._next[id(k)] = kids[i + 1] if i + 1 < len(kids) else None
            self._index(k)


def build_vs(doc, selected=()):
    v = types.ModuleType('vs')
    v.writes = []
    v.resets = []
    v.alerts = []
    v.answers = []

    class Rec:
        def __init__(self, obj):
            self.obj = obj

    layer_handles = ['LAYER%d' % i for i in range(len(doc.layers))]
    state = {'bools': {}, 'choices': {}, 'text': {}}
    lb = {'rows': [], 'cols': [], 'sel': -1, 'event': (False, 0, -1, -1),
          'sorting': None, 'updates': []}
    v.lb = lb
    v.dialog_state = state
    v.dialog_overrides = {}

    def GetParametricRecord(h):
        return Rec(h) if isinstance(h, Obj) else None

    def GetName(rec):
        return rec.obj.record

    def NumFields(rec):
        return len(rec.obj.order)

    def GetFldName(rec, i):
        return rec.obj.order[i - 1]

    def GetRField(h, pio, field):
        return h.fields.get(field, '') if isinstance(h, Obj) else ''

    def SetRField(h, pio, field, value):
        v.writes.append((h, field, h.fields.get(field), value))
        h.fields[field] = value
        return True

    def GetTypeN(h):
        return TYPE_PIO if isinstance(h, Obj) else TYPE_OTHER

    def ResetObject(h):
        v.resets.append(h)

    def FLayer():
        return layer_handles[0] if layer_handles else None

    def NextLayer(l):
        i = layer_handles.index(l)
        return layer_handles[i + 1] if i + 1 < len(layer_handles) else None

    def ActLayer():
        return layer_handles[0] if layer_handles else None

    def FIn3D(l):
        objs = doc.layers[layer_handles.index(l)]
        return objs[0] if objs else None

    def FInGroup(h):
        return h.children[0] if isinstance(h, Obj) and h.children else None

    def NextObj(h):
        return doc._next.get(id(h))

    def GetLayer(h):
        for name, objs in zip(layer_handles, doc.layers):
            stack = list(objs)
            while stack:
                o = stack.pop()
                if o is h:
                    return name
                stack.extend(o.children)
        return None

    def GetLName(h):
        return h if isinstance(h, str) else ''

    def ForEachObject(cb, crit):
        for o in selected:
            cb(o)

    def GetFName():
        return 'MOCK.vwx'

    def AlrtDialog(msg):
        v.alerts.append(msg)

    def AlertQuestion(q, advice, default, ok, cancel, third, fourth):
        return v.answers.pop(0) if v.answers else 0

    # ---- dialog stubs -------------------------------------------------------
    def CreateLayout(*a):
        return 1

    def CreateResizableLayout(*a):
        return 1

    def CreateStaticText(*a):
        return None

    def CreateCheckBox(dlg, item, txt):
        state['bools'].setdefault(item, False)

    def CreatePullDownMenu(dlg, item, w):
        state['choices'].setdefault(item, 0)

    def AddChoice(*a):
        return None

    def SelectChoice(dlg, item, idx, st):
        state['choices'][item] = idx

    def SetBooleanItem(dlg, item, val):
        state['bools'][item] = val

    def GetBooleanItem(dlg, item):
        return state['bools'].get(item, False)

    def GetSelectedChoiceIndex(dlg, item, x):
        return state['choices'].get(item, 0)

    def SetFirstLayoutItem(*a):
        return None

    def SetBelowItem(*a):
        return None

    def SetRightItem(*a):
        return None

    def RunLayoutDialog(dlg, handler):
        handler(12255, 0)
        for item, val in v.dialog_overrides.get('bools', {}).items():
            state['bools'][item] = val
        for item, val in v.dialog_overrides.get('choices', {}).items():
            state['choices'][item] = val
        handler(1, 0)
        return 1

    # ---- list browser -------------------------------------------------------
    def CreateLB(dlg, item, w, h):
        return None

    def InsertLBColumn(dlg, item, index, header, width):
        assert width and width > 0, 'width 0 crashes VW on macOS'
        lb['cols'].insert(index, header)
        return index

    def ShowLBHeader(dlg, item, show):
        return None

    def EnableLBColumnLines(dlg, item, on):
        return None

    def EnableLBSingleLineSelection(dlg, item, on):
        return None

    def EnableLBSorting(dlg, item, on):
        lb['sorting'] = on

    def EnableLBUpdates(dlg, item, on):
        lb['updates'].append(on)

    def RefreshLB(dlg, item):
        return True

    def InsertLBItem(dlg, item, index, text):
        lb['rows'].insert(index, {0: text})
        return index

    def SetLBItemInfo(dlg, item, row, col, text, image):
        assert image == -1 or image >= 0
        lb['rows'][row][col] = text
        return True

    def GetLBItemInfo(dlg, item, row, col):
        if row < 0 or row >= len(lb['rows']):
            return (False, '', -1)
        return (True, lb['rows'][row].get(col, ''), -1)

    def IsLBItemSelected(dlg, item, index):
        return index == lb['sel']

    def GetLBEventInfo(dlg, item):
        return lb['event']

    def CreatePushButton(dlg, item, text):
        return None

    def CreateEditText(dlg, item, text, width):
        state['text'][item] = text

    def SetItemText(dlg, item, text):
        state['text'][item] = text

    def GetItemText(dlg, item):
        return state['text'].get(item, '')

    for name, fn in list(locals().items()):
        if callable(fn) and name[0].isupper():
            setattr(v, name, fn)
    return v
