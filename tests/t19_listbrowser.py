"""In-dialog vocabulary review tests.

The documented trap: arrow keys and type-ahead move the highlight but report
rowIndex -1, so trusting the event writes a replacement onto whichever row was
last clicked. These drive the real handler through that exact sequence.
"""
import re
import sys
import types
from harness import CC, SANDBOX, Doc, Obj, Results, build_vs

R = Results()
check = R.check

ROWS = [('Cirrcuit', 1, 1), ('SWTCH', 40, 20), ('Pannel', 2, 2), ('PROC', 30, 15)]

# Control IDs from cc_tools.py's review dialog.
LB, EDIT, SET_BTN, CLEAR_BTN = 505, 507, 508, 509


def build():
    """Load the module with a dialog driver that replays a scripted session."""
    vs = build_vs(Doc([[Obj('Device', {'name': 'x', 'tag': 'x'})]]))

    def RunLayoutDialog(dlg, handler):
        handler(12255, 0)                 # setup populates the browser
        for step in vs.script:
            step(handler, vs)
        handler(1, 0)                     # OK
        return 1

    vs.RunLayoutDialog = RunLayoutDialog
    vs.script = []
    sys.modules['vs'] = vs
    src = re.sub(r'(?m)^run_cc_tools\(\)\s*$', '', open(CC).read())
    mod = types.ModuleType('cc_tools')
    exec(compile(src, CC, 'exec'), mod.__dict__)
    mod.BASE_FOLDER = SANDBOX
    return mod, vs


def click(row):
    def step(handler, vs):
        vs.lb['sel'] = row
        vs.lb['event'] = (True, -4, row, 0)      # selection change click
        handler(LB, 0)
    return step


def arrow_to(row):
    """Arrow-key navigation: the highlight moves, the event reports no row."""
    def step(handler, vs):
        vs.lb['sel'] = row
        vs.lb['event'] = (True, -8, -1, -1)
        handler(LB, 0)
    return step


def type_text(text):
    def step(handler, vs):
        vs.SetItemText(0, EDIT, text)
    return step


def press(item):
    def step(handler, vs):
        handler(item, 0)
    return step


# ── T1: the arrow-key case that would corrupt data ──────────────────────────
m, vs = build()
vs.script = [click(0), type_text('Circuit'),
             arrow_to(1), type_text('SWITCH'),
             click(3), type_text('PROCESSOR')]
out = m.review_vocabulary_dialog(ROWS)
check('T1 first edit landed on the clicked row', out.get('Cirrcuit') == 'Circuit',
      repr(out))
check('T1 arrow-key row got its own edit', out.get('SWTCH') == 'SWITCH', repr(out))
check('T1 third edit landed correctly', out.get('PROC') == 'PROCESSOR', repr(out))
check('T1 untouched row absent', 'Pannel' not in out, repr(out))
check('T1 exactly three replacements', len(out) == 3, repr(out))

# ── T2: an entrenched term is overridable despite heavy use ─────────────────
m2, vs2 = build()
vs2.script = [click(1), type_text('SWITCH'), press(SET_BTN)]
check('T2 high-frequency term replaceable',
      m2.review_vocabulary_dialog(ROWS) == {'SWTCH': 'SWITCH'})

# ── T3: Clear removes a pending replacement ─────────────────────────────────
m3, vs3 = build()
vs3.script = [click(0), type_text('Circuit'), press(SET_BTN), press(CLEAR_BTN)]
check('T3 cleared row not returned', m3.review_vocabulary_dialog(ROWS) == {})

# ── T4: a replacement equal to the term is ignored ──────────────────────────
m4, vs4 = build()
vs4.script = [click(1), type_text('SWTCH'), press(SET_BTN)]
check('T4 no-op replacement dropped', m4.review_vocabulary_dialog(ROWS) == {})

# ── T5: cancel is distinguishable from "no edits" ───────────────────────────
m5, vs5 = build()
vs5.RunLayoutDialog = lambda dlg, handler: (handler(12255, 0), 2)[1]
check('T5 cancel returns None', m5.review_vocabulary_dialog(ROWS) is None)

# ── T6: setup leaves the browser safe to use ────────────────────────────────
m6, vs6 = build()
m6.review_vocabulary_dialog(ROWS)
check('T6 sorting disabled (indices stay valid)', vs6.lb['sorting'] is False,
      repr(vs6.lb['sorting']))
check('T6 four columns created', len(vs6.lb['cols']) == 4, repr(vs6.lb['cols']))
check('T6 every row loaded', len(vs6.lb['rows']) == len(ROWS))
check('T6 updates disabled then re-enabled around the fill',
      vs6.lb['updates'] == [False, True], repr(vs6.lb['updates']))
check('T6 counts shown in the table',
      vs6.lb['rows'][1][1] == '40' and vs6.lb['rows'][1][2] == '20',
      repr(vs6.lb['rows'][1]))

# ── T7: phrases and tokens are separated for application ────────────────────
m7, _v = build()
tok, phr = m7.split_replacements({'Pannel': 'Panel', 'Grid Input': 'Grid'})
check('T7 single word -> token map', tok == {'pannel': 'Panel'}, repr(tok))
check('T7 multi word -> phrase map', phr == {'Grid Input': 'Grid'}, repr(phr))

R.report_and_exit()
