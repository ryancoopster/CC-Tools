"""Spellcheck tests.

The whole risk is false positives: this rewrites an engineering drawing whose
vocabulary is deliberately not English ('SWTCH', 'AVB Pri', 'EC-6A', 'pCON
grey'). A spellchecker that "corrects" those is worse than none at all.
"""
from harness import Doc, Results, load, dev, equip

R = Results()
check = R.check

# A stand-in word list. Passed explicitly so the suite does not depend on
# whatever /usr/share/dict/words happens to hold on this machine.
WORDS = {'circuit', 'switch', 'grid', 'array', 'primary', 'analog', 'patch',
         'panel', 'input', 'output', 'speaker', 'catwalk'}


def suspects_for(objs, ignore=frozenset()):
    m, _vs = load(Doc([objs]))
    freq, cased, counts = m.harvest_vocabulary(objs)
    return m, m.find_suspects(freq, cased, counts, set(ignore), WORDS)


# ── T1: a real typo is caught ───────────────────────────────────────────────
# 'Cirrcuit' once against many 'Circuit's -- the actual typo in the real job.
objs = [dev('AV Circuit %d' % i) for i in range(8)] + [dev('Catwalk 4 AV Cirrcuit 22')]
m, suspects = suspects_for(objs)
found = {s['token']: s['suggestion'] for s in suspects}
check('T1 typo detected', found.get('cirrcuit') == 'circuit', repr(found))
check('T1 nothing else flagged', len(suspects) == 1, repr(found))

# ── T2: consistent jargon is never flagged ──────────────────────────────────
jargon = []
for i in range(6):
    jargon += [dev('SWTCH 4.0%d' % i), dev('SPK 1.0%d HL ARRAY' % i),
               dev('PROC 2.0%d FF' % i)]
_m, s2 = suspects_for(jargon)
check('T2 consistent jargon never flagged', s2 == [],
      repr([(x['token'], x['suggestion']) for x in s2]))

# ── T3: a rare REAL word is spared ──────────────────────────────────────────
_m, s3 = suspects_for([dev('AV Circuit %d' % i) for i in range(8)] + [dev('Catwalk 1')])
check('T3 rare real word spared by the word list',
      all(x['token'] != 'catwalk' for x in s3), repr([x['token'] for x in s3]))

# ── T4: short tokens are never accused ──────────────────────────────────────
_m, s4 = suspects_for([dev('LAN %d' % i) for i in range(8)] + [dev('LAM 1')])
check('T4 3-letter token not accused', all(x['token'] != 'lam' for x in s4),
      repr([x['token'] for x in s4]))

# ── T5: rarity counts OBJECTS, not field occurrences ────────────────────────
# One typo shows up in a device's name AND tag AND its equipment item. Counting
# raw occurrences reads that as three independent uses and skips it.
d5 = dev('Grid Patch Pannel')
e5 = equip('Grid Patch Pannel')
rest = [dev('Grid Patch Panel %d' % i) for i in range(6)]
m5, _vs = load(Doc([[d5] + rest, [e5]]), associations={d5: e5})
scope = [d5, e5] + rest
freq, cased, counts = m5.harvest_vocabulary(scope)
check('T5 one typo counts as 2 objects, not 3 occurrences',
      counts['pannel'] == 2 and freq['pannel'] == 3,
      'objects=%r occurrences=%r' % (counts.get('pannel'), freq.get('pannel')))
accepted = {x['token']: x['suggestion']
            for x in m5.find_suspects(freq, cased, counts, set(), WORDS)}
check('T5 typo found despite repeating across linked fields',
      accepted.get('pannel') == 'panel', repr(accepted))

# ── T6: THE LINK REQUIREMENT - one fix, applied identically everywhere ──────
edits = m5.plan_spelling_edits(scope, accepted)
sync, _ua = m5.plan_link_sync(edits, {})
m5.apply_edits(edits + sync)
check('T6 device corrected', d5.fields['name'] == 'Grid Patch Panel',
      repr(d5.fields['name']))
check('T6 equipment corrected identically', e5.fields['name'] == 'Grid Patch Panel',
      repr(e5.fields['name']))
check('T6 link survived the fix', d5.fields['name'] == e5.fields['name'])

# ── T7: typo on ONE side only - sync repairs the pair ───────────────────────
d7 = dev('Grid Patch Pannel')
e7 = equip('Grid Patch Panel')
rest7 = [dev('Grid Patch Panel %d' % i) for i in range(6)]
m7, _vs = load(Doc([[d7] + rest7, [e7]]), associations={d7: e7})
scope7 = [d7, e7] + rest7
f7, c7, o7 = m7.harvest_vocabulary(scope7)
acc7 = {x['token']: x['suggestion']
        for x in m7.find_suspects(f7, c7, o7, set(), WORDS)}
ed7 = m7.plan_spelling_edits(scope7, acc7)
sy7, _u = m7.plan_link_sync(ed7, {})
m7.apply_edits(ed7 + sy7)
check('T7 one-sided typo converges the pair',
      d7.fields['name'] == e7.fields['name'] == 'Grid Patch Panel',
      '%r %r' % (d7.fields['name'], e7.fields['name']))

# ── T8: casing of the replaced token is preserved ───────────────────────────
m8, _vs = load(Doc([[dev('x')]]))
check('T8 uppercase stays uppercase',
      m8.apply_token_map('GRID PATCH PANNEL', {'pannel': 'panel'})
      == 'GRID PATCH PANEL')
check('T8 title case preserved',
      m8.apply_token_map('Pannel', {'pannel': 'panel'}) == 'Panel')
check('T8 digits and punctuation untouched',
      m8.apply_token_map('SWTCH 4.01-A', {'swtch': 'switch'}) == 'SWITCH 4.01-A')

# ── T9: the ignore list silences a token ────────────────────────────────────
_m, s9 = suspects_for(objs, ignore={'cirrcuit'})
check('T9 ignored token not flagged', all(x['token'] != 'cirrcuit' for x in s9),
      repr([x['token'] for x in s9]))

# ── T10: sentinels are neither read nor written ─────────────────────────────
sent = [dev('<DEVICE>', '<DEVICE>') for _ in range(5)] + [dev('AV Circuit 1')]
m10, _vs = load(Doc([sent]))
f10, _c, _o = m10.harvest_vocabulary(sent)
check('T10 <DEVICE> contributes no tokens', 'device' not in f10, repr(sorted(f10)))

d10 = dev('<DEVICE>', 'Grid Pannel')
m10b, _vs = load(Doc([[d10]]))
e10 = m10b.plan_spelling_edits([d10], {'pannel': 'panel'})
check('T10 sentinel name left alone', all(e['field'] != 'name' for e in e10),
      repr([(e['field'], e['old'], e['new']) for e in e10]))
check('T10 but its tag is corrected',
      any(e['field'] == 'tag' and e['new'] == 'Grid Panel' for e in e10),
      repr([(e['field'], e['old'], e['new']) for e in e10]))

R.report_and_exit()
