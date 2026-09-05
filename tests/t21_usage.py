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

# ── T4: config handling never leaks the key ─────────────────────────────────
cfg_path = m.claude_config_path()
if os.path.exists(cfg_path):
    os.remove(cfg_path)
config, error = m.load_claude_config()
check('T4 missing config is an error, not a crash', config is None and error)
check('T4 template created for the user to fill in', os.path.exists(cfg_path))
check('T4 message explains subscription does not cover it',
      'subscription' in error.lower(), repr(error))

with open(cfg_path, encoding='utf-8') as f:
    template = json.load(f)
check('T4 template ships an EMPTY key', template['api_key'] == '', repr(template))

config, error = m.load_claude_config()
check('T4 blank key rejected with guidance', config is None and 'api_key' in error)

SECRET = 'sk-ant-THIS-MUST-NEVER-APPEAR'
with open(cfg_path, 'w', encoding='utf-8') as f:
    json.dump({'api_key': SECRET, 'model': 'claude-opus-5'}, f)
config, error = m.load_claude_config()
check('T5 valid config loads', error is None and config['api_key'] == SECRET)

m.log_claude_usage(config['model'], 'with key present', usage, cost, 'note')
leaked = []
for name in os.listdir(SANDBOX):
    if name == m.CLAUDE_CONFIG_FILE:
        continue                     # the key legitimately lives here
    with open(os.path.join(SANDBOX, name), encoding='utf-8', errors='ignore') as f:
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
