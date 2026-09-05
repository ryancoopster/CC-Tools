"""Usage-accounting tests.

Cost estimates made before a run are guesses. This is the part that records
what was actually billed, so it has to be right about cache pricing, has to
log even when a call fails, and must never write the API key anywhere.
"""
import csv
import json
import os
import re
import shutil
import sys
import types
from mockvs import Obj, Doc, build_vs

CC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  'cc_tools.py')
SANDBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sandbox_out')
results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def load():
    vs = build_vs(Doc([[Obj('Device', {'name': 'x', 'tag': 'x'})]]))
    sys.modules['vs'] = vs
    src = re.sub(r'(?m)^run_cc_tools\(\)\s*$', '', open(CC).read())
    mod = types.ModuleType('m')
    exec(compile(src, CC, 'exec'), mod.__dict__)
    mod.BASE_FOLDER = SANDBOX
    return mod, vs


shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX, exist_ok=True)
m, vs = load()

# ── T1: cost maths, including the cache tiers ───────────────────────────────
cost = m.usage_cost('claude-opus-5', {'input_tokens': 1000000,
                                      'output_tokens': 0})
check('T1 1M input on Opus 5 = $5', abs(cost - 5.00) < 1e-6, repr(cost))

cost = m.usage_cost('claude-opus-5', {'input_tokens': 0,
                                      'output_tokens': 1000000})
check('T1 1M output on Opus 5 = $25', abs(cost - 25.00) < 1e-6, repr(cost))

cost = m.usage_cost('claude-sonnet-5', {'input_tokens': 1000000,
                                        'output_tokens': 1000000})
check('T1 Sonnet 5 priced separately', abs(cost - 12.00) < 1e-6, repr(cost))

cost = m.usage_cost('claude-opus-5', {'cache_read_input_tokens': 1000000})
check('T1 cache reads are a tenth of input', abs(cost - 0.50) < 1e-6, repr(cost))

cost = m.usage_cost('claude-opus-5', {'cache_creation_input_tokens': 1000000})
check('T1 cache writes cost more than input', abs(cost - 6.25) < 1e-6, repr(cost))

check('T1 unknown model returns None, not a wrong number',
      m.usage_cost('some-future-model', {'input_tokens': 100}) is None)

# ── T2: the log records what was billed ─────────────────────────────────────
usage = {'input_tokens': 20000, 'output_tokens': 10000,
         'cache_read_input_tokens': 5000, 'cache_creation_input_tokens': 0}
cost = m.usage_cost('claude-opus-5', usage)
path = m.log_claude_usage('claude-opus-5', 'draw schematic', usage, cost, 'note')
with open(path, newline='', encoding='utf-8') as f:
    rows = list(csv.reader(f))
header, row = rows[0], rows[1]
check('T2 header written once', len(rows) == 2, repr(len(rows)))
check('T2 every token class recorded',
      row[header.index('Input tokens')] == '20000'
      and row[header.index('Cache read')] == '5000'
      and row[header.index('Output tokens')] == '10000', repr(row))
check('T2 rate recorded alongside cost, so old rows stay interpretable',
      row[header.index('Input $/Mtok')] == '5.0', repr(row))
check('T2 cost matches the maths',
      abs(float(row[header.index('Cost USD')]) - cost) < 1e-4, repr(row))

m.log_claude_usage('claude-opus-5', 'second call', usage, cost)
calls, total = m.usage_totals()
check('T3 running total across calls', calls == 2 and abs(total - cost * 2) < 1e-4,
      'calls=%d total=%r' % (calls, total))

# ── T4: first run prompts for a key instead of demanding a file edit ────────
cfg_path = m.claude_config_path()
if os.path.exists(cfg_path):
    os.remove(cfg_path)

typed = {'api_key': 'sk-ant-TYPED-BY-THE-USER', 'model': 'claude-sonnet-5'}
m.ask_for_api_key = lambda existing=None: dict(typed)
config, error = m.load_claude_config()
check('T4 first run asks, then succeeds', error is None and config, repr(error))
check('T4 uses what was typed', config['api_key'] == typed['api_key'])
check('T4 model choice honoured', config['model'] == 'claude-sonnet-5',
      repr(config.get('model')))
check('T4 saved for next time', os.path.exists(cfg_path))

mode = oct(os.stat(cfg_path).st_mode)[-3:]
check('T4 saved readable only by this account', mode == '600', mode)

again, error2 = m.load_claude_config(prompt_if_missing=False)
check('T4 second run does not prompt', error2 is None and again['api_key'] == typed['api_key'])

# Declining the dialog must send nothing, and explain the billing.
os.remove(cfg_path)
m.ask_for_api_key = lambda existing=None: None
config3, error3 = m.load_claude_config()
check('T5 cancelling sends nothing', config3 is None and error3)
check('T5 explains subscription does not cover it',
      'subscription' in (error3 or '').lower(), repr(error3))
check('T5 nothing written when cancelled', not os.path.exists(cfg_path))

SECRET = 'sk-ant-THIS-MUST-NEVER-APPEAR'
m.save_claude_config({'api_key': SECRET, 'model': 'claude-opus-5'})
config, error = m.load_claude_config(prompt_if_missing=False)
check('T5 valid config loads', error is None and config['api_key'] == SECRET)

m.log_claude_usage(config['model'], 'with key present', usage, cost, 'note')
leaked = []
for name in os.listdir(SANDBOX):
    if name == m.CLAUDE_CONFIG_FILE:
        continue                     # the key legitimately lives here
    full = os.path.join(SANDBOX, name)
    if not os.path.isfile(full):
        continue
    with open(full, encoding='utf-8', errors='ignore') as f:
        if SECRET in f.read():
            leaked.append(name)
check('T5 key never written to any log or report', not leaked, repr(leaked))

# ── T6: a failed call still reports safely ──────────────────────────────────
reply, u, c, err = m.claude_request(
    {'api_key': SECRET, 'model': 'claude-opus-5', 'max_tokens': 10},
    [{'role': 'user', 'content': 'hi'}], purpose='unreachable')
check('T6 unreachable endpoint returns an error, not an exception',
      reply is None and err, repr(err))
check('T6 error text does not contain the key', SECRET not in (err or ''), repr(err))

# ── T8: the local tools work with no key at all ─────────────────────────────
# Nothing offline should consult, create, or prompt for credentials.
if os.path.exists(cfg_path):
    os.remove(cfg_path)

m8, vs8 = load()
prompted = {'yes': False}


def must_not_prompt(existing=None):
    prompted['yes'] = True
    return None


m8.ask_for_api_key = must_not_prompt
m8.ask_which_tools = lambda: [m8.TOOL_NORMALISE, m8.TOOL_MATCH, m8.TOOL_SPELL]
m8.ask_normalise_options = lambda: {
    'scope': m8.SCOPE_DOCUMENT, 'upper': True, 'trim': True, 'devices': True,
    'equipment': False, 'sockets': False, 'sync': True, 'preview': False}
m8.ask_match_options = lambda: {
    'scope': m8.SCOPE_DOCUMENT, 'devices': True, 'sockets': False,
    'action': m8.ACTION_EXPORT, 'include_empty': True}
m8.ask_spell_options = lambda: {
    'scope': m8.SCOPE_DOCUMENT, 'action': m8.ACTION_SPELL_EXPORT,
    'preview': False}
m8.run_cc_tools()

check('T8 offline tools never prompt for a key', not prompted['yes'])
check('T8 offline tools create no credential file', not os.path.exists(cfg_path))
check('T8 offline tools still did their work', len(vs8.alerts) >= 1, repr(vs8.alerts))

# And the dialog itself offers declining as a real answer.
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'cc_tools.py'), encoding='utf-8').read()
check('T8 key dialog offers a local-only choice',
      'Skip - use local tools only' in src)
check('T8 key dialog says the other tools need no key',
      'work offline without one' in src)

# ── T7: formatting is readable ──────────────────────────────────────────────
line = m.format_usage(usage, cost)
check('T7 usage line shows cached tokens and dollars',
      'cached' in line and '$' in line, repr(line))

print()
passed = sum(1 for _n, ok, _d in results if ok)
for name, ok, detail in results:
    print('%-4s %-52s %s' % ('PASS' if ok else 'FAIL', name, '' if ok else detail))
print('\n%d/%d passed' % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
