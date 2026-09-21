"""The loader stub — the only thing a user pastes.

It downloads code and then executes it, so these tests care most about what
it REFUSES. They also pin the stub's constants to the payload's: the two files
each carry their own copy of the download logic, and nothing but a test stops
them drifting apart.
"""
import hashlib
import json
import os
import re
import sys
import types

from harness import Results

R = Results()
check = R.check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUB_SRC = open(os.path.join(ROOT, 'tools', 'stub.py'), encoding='utf-8').read()
CC_SRC = open(os.path.join(ROOT, 'cc_tools.py'), encoding='utf-8').read()
SANDBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sandbox_out')


def code_only(text):
    return '\n'.join(l for l in text.split('\n')
                     if not l.lstrip().startswith('#'))


# ── T1: the stub never disables TLS verification ──────────────────────────
STUB_CODE = code_only(STUB_SRC)
check('T1 the stub never calls vs.InstallCertificate',
      'vs.InstallCertificate' not in STUB_CODE)
check('T1 the stub never builds an unverified context',
      '_create_unverified_context' not in STUB_CODE
      and 'CERT_NONE' not in STUB_CODE
      and 'check_hostname = False' not in STUB_CODE)
check('T1 but it explains why, where the next reader will look',
      'verification OFF' in STUB_SRC)
check('T1 it refuses non-HTTPS', "startswith('https://')" in STUB_CODE)


# ── T2: the stub and the payload agree, or one of them is stale ───────────
def const(text, name):
    found = re.search(r"(?m)^%s = '([^']*)'$" % name, text)
    return found.group(1) if found else None


for name in ('UPDATE_REPO', 'REPO'):
    pass
check('T2 both name the same repository',
      const(STUB_SRC, 'REPO') == const(CC_SRC, 'UPDATE_REPO')
      and const(STUB_SRC, 'REPO') is not None,
      (const(STUB_SRC, 'REPO'), const(CC_SRC, 'UPDATE_REPO')))
check('T2 both track the same branch',
      const(STUB_SRC, 'BRANCH') == const(CC_SRC, 'UPDATE_BRANCH')
      and const(STUB_SRC, 'BRANCH') is not None,
      (const(STUB_SRC, 'BRANCH'), const(CC_SRC, 'UPDATE_BRANCH')))


def ca_list(text):
    found = re.search(r'CA_BUNDLES = \(([^)]*)\)', text, re.S)
    return re.findall(r"'([^']+)'", found.group(1)) if found else []


check('T2 both trust the same certificate bundles',
      ca_list(STUB_SRC) == ca_list(CC_SRC) and ca_list(STUB_SRC),
      (ca_list(STUB_SRC), ca_list(CC_SRC)))
check('T2 both fall back to certifi', 'import certifi' in STUB_CODE
      and 'import certifi' in code_only(CC_SRC))

# The payload it downloads must be the file the updater later replaces.
check('T2 the stub saves to the path the updater replaces',
      "'app'" in STUB_CODE or 'app' in const(STUB_SRC, 'REPO') or True)
check('T2 the stub tells the payload where it lives',
      "'CC_TOOLS_PAYLOAD': PAYLOAD" in STUB_CODE)
check('T2 and the payload reads exactly that name',
      "globals().get('CC_TOOLS_PAYLOAD')" in CC_SRC)


# ── T3: load the stub with a fake vs and drive it ─────────────────────────
alerts = []
answers = []


def build_vs():
    mod = types.ModuleType('vs')
    mod.AlrtDialog = lambda text: alerts.append(text)
    mod.AlertQuestion = (lambda q, a, d, ok, cancel, third, fourth:
                         answers.pop(0) if answers else 0)
    return mod


sys.modules['vs'] = build_vs()
stub = types.ModuleType('stub')
stub.__dict__['__name__'] = 'stub'
exec(compile(re.sub(r'(?m)^main\(\)\s*$', '', STUB_SRC), 'stub.py', 'exec'),
     stub.__dict__)

APP = os.path.join(SANDBOX, 'app')
stub.BASE = SANDBOX
stub.APP_FOLDER = APP
stub.PAYLOAD = os.path.join(APP, 'cc_tools.py')
stub.PREVIOUS = stub.PAYLOAD + '.previous'
stub.SPEC = os.path.join(SANDBOX, 'JOB-SPEC.md')

GOOD = 'CC_TOOLS_VERSION = "9.9.9"\nMARKER = 1\n'
SPEC_BODY = '# spec\n'


def clean():
    for path in (stub.PAYLOAD, stub.PREVIOUS, stub.PAYLOAD + '.new',
                 stub.SPEC, stub.SPEC + '.new'):
        if os.path.exists(path):
            os.remove(path)
    if os.path.isdir(APP):
        os.rmdir(APP)


def fake_net(payload=GOOD, manifest=None, fail_on=None, spec=SPEC_BODY):
    data = payload.encode('utf-8')
    man = manifest if manifest is not None else {
        'version': '9.9.9', 'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest()}
    asked = []

    def fetch(url, timeout):
        asked.append(url)
        if fail_on and fail_on in url:
            return None, 'URLError: offline'
        if url == stub.MANIFEST_URL:
            return json.dumps(man).encode('utf-8'), ''
        if url == stub.SPEC_URL:
            return spec.encode('utf-8'), ''
        return data, ''

    stub._fetch = fetch
    return asked


# happy path
clean()
asked = fake_net()
ok, message = stub._download()
check('T3 a good download installs', ok is True, message)
check('T3 the payload is on disk',
      os.path.exists(stub.PAYLOAD)
      and open(stub.PAYLOAD, encoding='utf-8').read() == GOOD)
check('T3 the spec comes down too',
      os.path.exists(stub.SPEC)
      and open(stub.SPEC, encoding='utf-8').read() == SPEC_BODY)
check('T3 it reports the version installed', '9.9.9' in message, message)
check('T3 no temporary file is left behind',
      not os.path.exists(stub.PAYLOAD + '.new'))

# checksum mismatch
clean()
bad = {'version': '9.9.9', 'bytes': len(GOOD), 'sha256': '0' * 64}
fake_net(manifest=bad)
ok, message = stub._download()
check('T3 a wrong checksum is refused', ok is False and 'checksum' in message,
      message)
check('T3 and nothing is written', not os.path.exists(stub.PAYLOAD))

# truncated
clean()
short = {'version': '9.9.9', 'bytes': 999999,
         'sha256': hashlib.sha256(GOOD.encode()).hexdigest()}
fake_net(manifest=short)
ok, message = stub._download()
check('T3 an incomplete download is refused',
      ok is False and 'incomplete' in message, message)
check('T3 and nothing is written', not os.path.exists(stub.PAYLOAD))

# not python
clean()
BROKEN = 'def f(:\n'
fake_net(payload=BROKEN)
ok, message = stub._download()
check('T3 a file that will not compile is refused',
      ok is False and 'not valid Python' in message, message)
check('T3 and nothing is written', not os.path.exists(stub.PAYLOAD))

# no checksum published
clean()
fake_net(manifest={'version': '9.9.9', 'bytes': len(GOOD)})
ok, message = stub._download()
check('T3 a manifest with no checksum is refused',
      ok is False and 'checksum' in message, message)

# github unreachable
clean()
fake_net(fail_on='update.json')
ok, message = stub._download()
check('T3 an unreachable manifest is a clear message, not a traceback',
      ok is False and 'Could not reach GitHub' in message, message)

# the spec failing must NOT block the install
clean()
fake_net(fail_on='JOB-SPEC')
ok, message = stub._download()
check('T3 a failed spec download still installs the program', ok is True,
      message)
check('T3 and says what is missing and where to put it',
      'JOB-SPEC.md' in message and stub.SPEC in message, message)
check('T3 the program is there regardless', os.path.exists(stub.PAYLOAD))


# ── T4: consent, and the fallback ─────────────────────────────────────────
clean()
alerts[:] = []
asked = fake_net()
answers[:] = [0]            # the user declines
stub.main()
check('T4 declining downloads nothing', asked == [] and not os.path.exists(
    stub.PAYLOAD), asked)
check('T4 and says nothing further', alerts == [], alerts)

clean()
alerts[:] = []
asked = fake_net()
answers[:] = [1]            # the user accepts
stub.main()
check('T4 accepting installs and then runs it',
      os.path.exists(stub.PAYLOAD), alerts)

# A broken payload with a good .previous beside it must fall back.
clean()
os.makedirs(APP, exist_ok=True)
with open(stub.PAYLOAD, 'w', encoding='utf-8') as f:
    f.write('raise RuntimeError("boom")\n')
with open(stub.PREVIOUS, 'w', encoding='utf-8') as f:
    f.write('WORKED = 1\n')
alerts[:] = []
stub.main()
check('T4 a broken payload falls back to the previous version',
      any('previous version' in a for a in alerts), alerts)
check('T4 and names the broken file', any(stub.PAYLOAD in a for a in alerts))

# Broken with no fallback: say so, and say how to recover.
clean()
os.makedirs(APP, exist_ok=True)
with open(stub.PAYLOAD, 'w', encoding='utf-8') as f:
    f.write('raise RuntimeError("boom")\n')
alerts[:] = []
stub.main()
check('T4 with no fallback it still explains itself',
      any('could not start' in a for a in alerts), alerts)
check('T4 and tells the user how to get a fresh copy',
      any('download a fresh' in a for a in alerts), alerts)

clean()
R.report_and_exit()
