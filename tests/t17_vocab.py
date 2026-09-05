"""Vocabulary-list tests: spellcheck as reviewable find-and-replace.

Frequency shows what is CONSISTENT, not what is CORRECT -- 'SWTCH' used
everywhere is an entrenched mistake, not vocabulary. These cover the route that
lets any term be overridden, and confirm dropdown and library fields are never
touched.
"""
import csv
from harness import Doc, Obj, Results, load, full_dev, equip, sock

R = Results()
check = R.check

devs = [full_dev('SWTCH 4.0%d' % i) for i in range(6)]
eqs = [equip('SWTCH 4.0%d' % i) for i in range(6)]
m, vs = load(Doc([devs, eqs]))
scope = devs + eqs
freq, cased, objs = m.harvest_vocabulary(scope)

# ── T1: an entrenched term appears, but is not auto-flagged ─────────────────
check('T1 entrenched term is in the vocabulary', 'swtch' in freq, repr(sorted(freq)))
check('T1 counted across objects', objs['swtch'] == 12, repr(objs.get('swtch')))
check('T1 spellchecker does not flag it on its own',
      m.find_suspects(freq, cased, objs, set(), {'switch'}) == [])

# ── T2: dropdowns and library values never enter the vocabulary ─────────────
for term in ['meyer', 'sound', 'galaxy', 'generic', 'right', 'rack']:
    check('T2 %-8s not harvested' % term, term not in freq, 'leaked: %r' % term)

# ── T3: export lists every term with a blank Replace column ─────────────────
path, count = m.export_vocabulary_csv(freq, cased, objs, [])
with open(path, newline='', encoding='utf-8') as f:
    rows = list(csv.reader(f))
header, body = rows[0], rows[1:]
check('T3 header has Replace with', header[-1] == 'Replace with', repr(header))
check('T3 every term present', count == len(freq) == len(body),
      'count=%d freq=%d body=%d' % (count, len(freq), len(body)))
check('T3 SWTCH listed', any(r[0].lower() == 'swtch' for r in body))

# ── T4: fill it in, read it back, apply globally ────────────────────────────
with open(path, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(header)
    for r in body:
        r = list(r)
        if r[0].lower() == 'swtch':
            r[-1] = 'SWITCH'
        w.writerow(r)

token_map, phrase_map, error = m.load_vocabulary_csv()
check('T4 csv read without error', error is None, repr(error))
check('T4 replacement picked up', token_map == {'swtch': 'SWITCH'}, repr(token_map))

edits = m.plan_spelling_edits(scope, token_map, phrase_map)
sync, _ua = m.plan_link_sync(edits, {})
m.apply_edits(edits + sync)
check('T4 every device renamed',
      all(d.fields['name'].startswith('SWITCH') for d in devs),
      repr([d.fields['name'] for d in devs]))
check('T4 every equipment item followed',
      all(e.fields['name'].startswith('SWITCH') for e in eqs),
      repr([e.fields['name'] for e in eqs]))
check('T4 links still pair up',
      sorted(d.fields['name'] for d in devs) == sorted(e.fields['name'] for e in eqs))
check('T4 library fields untouched',
      devs[0].fields['make'] == 'Meyer Sound'
      and devs[0].fields['description'] == 'Meyer Sound_2100-LFC',
      repr(devs[0].fields))

# ── T5: a missing or unfilled sheet is an error, not a silent no-op ─────────
import os
os.remove(path)
os.remove(os.path.join(m.BASE_FOLDER, m.VOCAB_FILE)) if os.path.exists(
    os.path.join(m.BASE_FOLDER, m.VOCAB_FILE)) else None
tok, phr, err = m.load_vocabulary_csv()
check('T5 missing sheet reports why', not tok and not phr and err, repr(err))

# ── T6: multi-word terms act as literal find-and-replace ────────────────────
d6 = [full_dev('Grid Input Patch %d' % i) for i in range(4)]
m6, _v = load(Doc([d6]))
e6 = m6.plan_spelling_edits(d6, {}, {'Grid Input Patch': 'Grid Patch'})
m6.apply_edits(e6)
check('T6 phrase replaced', d6[0].fields['name'] == 'Grid Patch 0',
      repr(d6[0].fields['name']))
check('T6 longest phrase applied first',
      m6.apply_phrase_map('Grid Input Patch',
                          {'Grid': 'GRD', 'Grid Input Patch': 'GIP'}) == 'GIP')

# ── T7: sockets and circuits are in scope; their dropdowns are not ──────────
sk = [sock('LAN_IN %d' % i) for i in range(4)]
ci = [Obj('Circuit', {'Label': 'Spare Feed', 'Number': '', 'Cable': '',
                      'Signal': 'AVB Pri', 'Src_Dev_Name': 'SWTCH 4.01'})]
m7, _v = load(Doc([sk, ci]))
f7, _c7, _o7 = m7.harvest_vocabulary(sk + ci)
check('T7 socket names harvested', 'lan' in f7 or 'in' in f7, repr(sorted(f7)))
check('T7 circuit Label harvested', 'spare' in f7, repr(sorted(f7)))
check('T7 circuit Signal dropdown ignored', 'avb' not in f7, repr(sorted(f7)))
check('T7 circuit endpoint cache ignored', 'swtch' not in f7, repr(sorted(f7)))

R.report_and_exit()
