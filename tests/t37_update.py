"""The GitHub update check.

This downloads code and then executes it, so the tests care most about the
cases where it must REFUSE: a bad checksum, a short file, something that will
not compile, a URL that is not ours, and a certificate store that cannot
verify anything.
"""
import hashlib
import json
import os
import sys
import types

from harness import Doc, Results, load, dev

R = Results()
check = R.check
m, vs = load(Doc([[dev('x')]]))

STATE = os.path.join(m.BASE_FOLDER, 'update_state.json')
PREFS = os.path.join(m.BASE_FOLDER, 'preferences.json')


def clean():
    for path in (STATE, PREFS):
        if os.path.exists(path):
            os.remove(path)


def manifest_for(source, version='9.9.9', notes=('Did a thing',)):
    data = source.encode('utf-8')
    return {'version': version, 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'min_stub': 1, 'notes': list(notes)}


GOOD = 'CC_TOOLS_VERSION = "9.9.9"\n\ndef f():\n    return 1\n'
REAL_FETCH = m.fetch_url             # before anything replaces it


def stub_fetch(payload=None, manifest=None, error=''):
    """Replace fetch_url. Records what was asked for."""
    asked = []

    def fetch(url, timeout=None, limit=None):
        asked.append(url)
        if error:
            return None, error
        if url == m.UPDATE_MANIFEST_URL:
            return json.dumps(manifest).encode('utf-8'), ''
        return (payload or '').encode('utf-8'), ''

    m.fetch_url = fetch
    return asked


# ── T1: version comparison ────────────────────────────────────────────────
check('T1 0.9.10 is newer than 0.9.9', m.is_newer('0.9.10', '0.9.9'))
check('T1 0.9.0 is not newer than 0.9.0', not m.is_newer('0.9.0', '0.9.0'))
check('T1 0.9.0 is not newer than 0.10.0', not m.is_newer('0.9.0', '0.10.0'))
check('T1 1.0 beats 0.9.99', m.is_newer('1.0', '0.9.99'))
check('T1 a short version pads rather than losing', not m.is_newer('1.0', '1.0.1'))
check('T1 rubbish does not crash or look newer',
      not m.is_newer('', '0.1.0') and not m.is_newer('banana', '0.1.0'))
check('T1 a tagged version still parses', m.is_newer('v0.9.1', '0.9.0'))


# ── T2: the download must refuse anything it cannot verify ────────────────
good_manifest = manifest_for(GOOD)

stub_fetch(payload=GOOD, manifest=good_manifest)
source, error = m.download_update(good_manifest)
check('T2 a good download is accepted', source == GOOD and not error, error)

bad = dict(good_manifest, sha256='0' * 64)
stub_fetch(payload=GOOD, manifest=bad)
source, error = m.download_update(bad)
check('T2 a wrong checksum is refused', source is None and 'checksum' in error,
      error)

short = dict(good_manifest, bytes=999999)
stub_fetch(payload=GOOD, manifest=short)
source, error = m.download_update(short)
check('T2 a wrong byte count is refused', source is None and 'bytes' in error,
      error)

nohash = dict(good_manifest)
nohash.pop('sha256')
stub_fetch(payload=GOOD, manifest=nohash)
source, error = m.download_update(nohash)
check('T2 a manifest with no checksum is refused outright',
      source is None and 'checksum' in error, error)
check('T2 and it refuses BEFORE fetching the payload',
      True)  # asserted below by call count

asked = stub_fetch(payload=GOOD, manifest=nohash)
m.download_update(nohash)
check('T2 nothing is downloaded when there is no checksum to check it against',
      m.UPDATE_PAYLOAD_URL not in asked, asked)

BROKEN = 'def f(:\n  pass\n'
broken_manifest = manifest_for(BROKEN)
stub_fetch(payload=BROKEN, manifest=broken_manifest)
source, error = m.download_update(broken_manifest)
check('T2 a file that will not compile is refused even with a valid checksum',
      source is None and 'compile' in error, error)

stub_fetch(error='URLError: offline')
source, error = m.download_update(good_manifest)
check('T2 a network failure is an error, not an exception',
      source is None and 'offline' in error, error)


# ── T3: the URLs are ours and cannot be redirected ────────────────────────
check('T3 both URLs are HTTPS',
      m.UPDATE_MANIFEST_URL.startswith('https://')
      and m.UPDATE_PAYLOAD_URL.startswith('https://'))
check('T3 both point at the real repository',
      m.UPDATE_REPO in m.UPDATE_MANIFEST_URL
      and m.UPDATE_REPO in m.UPDATE_PAYLOAD_URL)

# A manifest naming its own download location would be a redirect-to-anywhere.
hostile = dict(good_manifest, url='https://evil.example/x.py',
               payload_url='https://evil.example/x.py')
asked = stub_fetch(payload=GOOD, manifest=hostile)
m.download_update(hostile)
check('T3 a manifest cannot redirect the download',
      asked == [m.UPDATE_PAYLOAD_URL], asked)

SRC = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'cc_tools.py'), encoding='utf-8').read()
# Comments explain WHY these are forbidden, so the check is against code only.
CODE = '\n'.join(line for line in SRC.split('\n')
                 if not line.lstrip().startswith('#'))
check('T3 vs.InstallCertificate is never called -- it disables verification',
      'vs.InstallCertificate()' not in CODE)
check('T3 no unverified SSL context is ever built',
      '_create_unverified_context' not in CODE and 'CERT_NONE' not in CODE)
check('T3 but the reason is written down where the next reader will see it',
      'InstallCertificate' in SRC and 'verification OFF' in SRC)

data, err = REAL_FETCH('http://example.com/x.py')
check('T3 fetch_url refuses a plain-HTTP URL',
      data is None and 'HTTPS' in err, err)


# ── T4: interval and back-off ─────────────────────────────────────────────
DAY = 86400.0
prefs_on = {'check_for_updates': True, 'update_interval_days': 7.0}
prefs_off = {'check_for_updates': False, 'update_interval_days': 0.0}
fresh = dict(m.UPDATE_STATE_DEFAULTS)

check('T4 nothing is due when checking is off',
      not m.update_check_due(fresh, prefs_off, 1000.0))
check('T4 a first run is due', m.update_check_due(fresh, prefs_on, 1000.0))
check('T4 not due four days into a seven-day interval',
      not m.update_check_due(dict(fresh, last_check=1000.0), prefs_on,
                             1000.0 + 4 * DAY))
check('T4 due eight days in',
      m.update_check_due(dict(fresh, last_check=1000.0), prefs_on,
                         1000.0 + 8 * DAY))
check('T4 an interval of 0 means every launch',
      m.update_check_due(dict(fresh, last_check=1000.0),
                         {'check_for_updates': True,
                          'update_interval_days': 0.0}, 1001.0))
check('T4 two failures back off to a day even when set to every launch',
      not m.update_check_due(dict(fresh, last_check=1000.0, failures=2),
                             {'check_for_updates': True,
                              'update_interval_days': 0.0}, 1000.0 + 600))
check('T4 and it checks again once that day is up',
      m.update_check_due(dict(fresh, last_check=1000.0, failures=2),
                         {'check_for_updates': True,
                          'update_interval_days': 0.0}, 1000.0 + 2 * DAY))
check('T4 a clock that went backwards does not park the check forever',
      m.update_check_due(dict(fresh, last_check=9e9), prefs_on, 1000.0))


# ── T5: state survives a round trip and never lands in preferences.json ───
clean()
state = dict(m.UPDATE_STATE_DEFAULTS, last_check=123.5, failures=3,
             skipped_version='9.9.9', consent_asked=True)
m.save_update_state(state)
back = m.load_update_state()
check('T5 state round-trips', back['last_check'] == 123.5
      and back['failures'] == 3 and back['skipped_version'] == '9.9.9'
      and back['consent_asked'] is True, back)

with open(STATE, 'w', encoding='utf-8') as f:
    f.write('{ not json')
check('T5 a corrupt state file falls back to defaults, it does not raise',
      m.load_update_state() == m.UPDATE_STATE_DEFAULTS)

with open(STATE, 'w', encoding='utf-8') as f:
    json.dump({'last_check': 'yesterday', 'failures': None}, f)
back = m.load_update_state()
check('T5 nonsense values fall back per key',
      back['last_check'] == 0.0 and back['failures'] == 0, back)

# The bookkeeping must not live in preferences.json, which save_prefs rewrites
# from PREF_DEFAULTS keys alone -- anything else there is destroyed.
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=True,
                  update_interval_days=1.0))
saved = json.load(open(PREFS, encoding='utf-8'))
check('T5 the two user-facing settings DO persist in preferences.json',
      saved.get('check_for_updates') is True
      and saved.get('update_interval_days') == 1.0, saved)
check('T5 and the machine bookkeeping does not',
      'last_check' not in saved and 'skipped_version' not in saved, saved)
check('T5 preferences round-trip the toggle',
      m.load_prefs()['check_for_updates'] is True)


# ── T6: consent gates the network entirely ────────────────────────────────
clean()
asked = stub_fetch(payload=GOOD, manifest=good_manifest)
vs.dialog_overrides = {}


def refuse_dialog(dlg, handler):
    handler(12255, 0)
    return 0            # the user closed the consent dialog


vs.RunLayoutDialog = refuse_dialog
installed, status = m.run_update_check()
check('T6 declining consent makes no network call at all', asked == [], asked)
check('T6 and installs nothing', installed is False and status == '',
      (installed, status))
check('T6 and asks again next time -- consent was not recorded',
      m.load_update_state()['consent_asked'] is False)

clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=False))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
asked = stub_fetch(payload=GOOD, manifest=good_manifest)
installed, status = m.run_update_check()
check('T6 answering "no" means no network call, ever', asked == [], asked)


# ── T7: the offer, and what each answer does ──────────────────────────────
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=True,
                  update_interval_days=0.0))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))

installs = []
REAL_INSTALL = m.install_update      # keep it; T9 puts it back
m.install_update = lambda src: (installs.append(src) or (True, ''))

stub_fetch(payload=GOOD, manifest=good_manifest)
vs.answers = [m.UPDATE_ANSWER_NOW]
installed, status = m.run_update_check()
check('T7 "Update now" installs', installed is True and installs, status)
check('T7 and says it takes effect next run',
      'menu again' in status, status)

installs[:] = []
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=True,
                  update_interval_days=0.0))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
stub_fetch(payload=GOOD, manifest=good_manifest)
vs.answers = [m.UPDATE_ANSWER_SKIP]
installed, status = m.run_update_check()
check('T7 "Skip" installs nothing', installed is False and not installs)
check('T7 and remembers the version skipped',
      m.load_update_state()['skipped_version'] == '9.9.9')

stub_fetch(payload=GOOD, manifest=good_manifest)
vs.answers = [m.UPDATE_ANSWER_NOW]
installed, status = m.run_update_check()
check('T7 a skipped version is not offered again', installed is False
      and not installs, status)

# ...but a newer one is.
newer = manifest_for(GOOD, version='9.9.10')
stub_fetch(payload=GOOD, manifest=newer)
vs.answers = [m.UPDATE_ANSWER_NOW]
installed, status = m.run_update_check()
check('T7 a version newer than the skipped one IS offered',
      installed is True, status)

# "Ask me later" must not advance the interval, or later means much later.
installs[:] = []
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=True,
                  update_interval_days=7.0))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
stub_fetch(payload=GOOD, manifest=good_manifest)
vs.answers = [m.UPDATE_ANSWER_LATER]
installed, status = m.run_update_check()
check('T7 "Ask me later" installs nothing', installed is False and not installs)
check('T7 and does not record a skip',
      m.load_update_state()['skipped_version'] == '')

# An unrecognised answer must never install: the button mapping is assumed.
installs[:] = []
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=True,
                  update_interval_days=0.0))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
stub_fetch(payload=GOOD, manifest=good_manifest)
vs.answers = [77]
installed, status = m.run_update_check()
check('T7 an unexpected dialog answer installs nothing',
      installed is False and not installs, status)


# ── T8: failure is silent unless asked for by hand ────────────────────────
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=True,
                  update_interval_days=0.0))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
stub_fetch(error='URLError: offline')
installed, status = m.run_update_check()
check('T8 an offline automatic check says nothing to the user',
      installed is False and status == '', status)
check('T8 but records the failure so Preferences can show it',
      'offline' in m.load_update_state()['last_error'])
check('T8 and counts it, for the back-off',
      m.load_update_state()['failures'] == 1)

installed, status = m.run_update_check(force=True)
check('T8 a manual check DOES report the failure',
      'Could not check' in status and 'offline' in status, status)

# Up to date, asked by hand, should say so rather than nothing.
clean()
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
same = manifest_for(GOOD, version=m.CC_TOOLS_VERSION)
stub_fetch(payload=GOOD, manifest=same)
installed, status = m.run_update_check(force=True)
check('T8 a manual check confirms when there is nothing new',
      'latest version' in status, status)

# A manual check ignores both the interval and an earlier skip.
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=False))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True,
                         last_check=9e9, skipped_version='9.9.9'))
stub_fetch(payload=GOOD, manifest=good_manifest)
vs.answers = [m.UPDATE_ANSWER_SKIP]
installed, status = m.run_update_check(force=True)
check('T8 a manual check runs even with updates off and a version skipped',
      'Skipped' in status, status)


# ── T9: installing writes atomically and keeps the old file ───────────────
clean()
m.install_update = REAL_INSTALL     # the real one again, for these
app = os.path.join(m.BASE_FOLDER, 'app')
os.makedirs(app, exist_ok=True)
live = os.path.join(app, 'cc_tools.py')
with open(live, 'w', encoding='utf-8') as f:
    f.write('OLD = 1\n')

m.__dict__['CC_TOOLS_PAYLOAD'] = live
ok, detail = m.install_update(GOOD)
check('T9 the payload is replaced', ok is True, detail)
check('T9 the new contents are there',
      open(live, encoding='utf-8').read() == GOOD)
check('T9 the previous version is kept',
      os.path.exists(live + '.previous')
      and open(live + '.previous', encoding='utf-8').read() == 'OLD = 1\n')
check('T9 no temporary file is left behind', not os.path.exists(live + '.new'))

m.__dict__['CC_TOOLS_PAYLOAD'] = ''
ok, detail = m.install_update(GOOD)
check('T9 pasted-whole says so instead of writing a file nothing loads',
      ok is False and 'pasted' in detail, detail)

m.__dict__['CC_TOOLS_PAYLOAD'] = os.path.join(app, 'gone.py')
ok, detail = m.install_update(GOOD)
check('T9 a missing payload is refused', ok is False and 'missing' in detail,
      detail)

for path in (live, live + '.previous', live + '.new'):
    if os.path.exists(path):
        os.remove(path)
os.rmdir(app)


# ── T10: the release notes reach the user ─────────────────────────────────
notes = m.update_notes_text({'notes': ['One', 'Two', 'Three']})
check('T10 every note is shown', notes == ['One', 'Two', 'Three'], notes)
many = m.update_notes_text({'notes': ['n%d' % i for i in range(40)]}, limit=5)
check('T10 a long list is capped and says how many were dropped',
      len(many) == 6 and '35 more' in many[-1], many)
check('T10 no notes says so plainly, rather than showing an empty list',
      'No release notes' in m.update_notes_text({'notes': []})[0])

m.__dict__['CC_TOOLS_PAYLOAD'] = '/tmp/x/cc_tools.py'
advice = m.update_prompt_advice(good_manifest)
check('T10 the prompt carries the notes', 'Did a thing' in advice)
check('T10 the prompt says where it installs', '/tmp/x/cc_tools.py' in advice)
check('T10 the prompt warns it applies next run', 'next time' in advice)


# ── T11: the released manifest matches the file it describes ──────────────
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mpath = os.path.join(root, 'update.json')
if os.path.exists(mpath):
    published = json.load(open(mpath, encoding='utf-8'))
    raw = open(os.path.join(root, 'cc_tools.py'), 'rb').read()
    check('T11 update.json matches cc_tools.py byte count',
          published.get('bytes') == len(raw),
          (published.get('bytes'), len(raw)))
    check('T11 update.json matches cc_tools.py checksum',
          published.get('sha256') == hashlib.sha256(raw).hexdigest())
    check('T11 update.json version matches CC_TOOLS_VERSION',
          published.get('version') == m.CC_TOOLS_VERSION,
          (published.get('version'), m.CC_TOOLS_VERSION))
else:
    check('T11 no update.json published yet', True)


# ── T12: a payload needing a newer loader is refused, not installed ───────
clean()
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
m.__dict__['CC_TOOLS_STUB_VERSION'] = 2
stub_fetch(payload=GOOD, manifest=dict(good_manifest, min_stub=5))
manifest, error = m.fetch_manifest()
check('T12 a payload needing a newer loader is refused',
      manifest is None and 'newer loader' in error, error)
check('T12 and the message says both versions',
      '5' in error and '2' in error, error)

stub_fetch(payload=GOOD, manifest=dict(good_manifest, min_stub=2))
manifest, error = m.fetch_manifest()
check('T12 a payload the loader can run is accepted',
      manifest is not None and not error, error)

stub_fetch(payload=GOOD, manifest=dict(good_manifest, min_stub='nonsense'))
manifest, error = m.fetch_manifest()
check('T12 an unparseable min_stub falls back to 1 rather than blocking',
      manifest is not None and manifest['min_stub'] == 1, error)
del m.__dict__['CC_TOOLS_STUB_VERSION']


# ── T13: the device list refreshes, but never over the user's own edits ───
import hashlib as _h
SPEC_BODY = '# spec v2\n'
SPEC_PATH = os.path.join(m.BASE_FOLDER, 'JOB-SPEC.md')


def spec_net(body=SPEC_BODY, error=''):
    def fetch(url, timeout=None, limit=None):
        if error:
            return None, error
        return body.encode('utf-8'), ''
    m.fetch_url = fetch


def clear_specs():
    for name in m.GOLDEN_FILES:
        path = os.path.join(m.BASE_FOLDER, name)
        if os.path.exists(path):
            os.remove(path)


clear_specs()
spec_net()
state, note = m.refresh_spec(dict(m.UPDATE_STATE_DEFAULTS))
check('T13 a missing device list is written', note == 'device list updated'
      and os.path.exists(m.golden_path()), (note, m.golden_path()))
check('T13 and its hash is recorded',
      state['spec_sha'] == _h.sha256(SPEC_BODY.encode()).hexdigest())

# Unchanged since we wrote it -> replaced by the newer one.
spec_net('# spec v3\n')
state, note = m.refresh_spec(state)
check('T13 an untouched list is brought up to date',
      note == 'device list updated'
      and open(m.golden_path(), encoding='utf-8').read() == '# spec v3\n', note)

# Edited by hand -> left alone, and said out loud.
with open(m.golden_path(), 'w', encoding='utf-8') as f:
    f.write('# spec v3 plus MY OWN DEVICE\n')
spec_net('# spec v4\n')
state2, note = m.refresh_spec(state)
check('T13 a hand-edited list is NOT overwritten',
      'your own changes' in note, note)
check('T13 and the edit survives',
      'MY OWN DEVICE' in open(m.golden_path(), encoding='utf-8').read())
check('T13 and the recorded hash is not advanced past it',
      state2['spec_sha'] == state['spec_sha'])

# A list that was already there before CC Tools knew about it.
clear_specs()
with open(SPEC_PATH, 'w', encoding='utf-8') as f:
    f.write('# someone put this here\n')
spec_net('# spec v5\n')
state3, note = m.refresh_spec(dict(m.UPDATE_STATE_DEFAULTS))
check('T13 a list CC Tools never wrote is left alone',
      'may be yours' in note, note)
check('T13 and it survives',
      'someone put this here' in open(SPEC_PATH, encoding='utf-8').read())

# It writes to whichever accepted name is in use.
clear_specs()
alt = os.path.join(m.BASE_FOLDER, 'devices.md')
with open(alt, 'w', encoding='utf-8') as f:
    f.write('# old\n')
seed = dict(m.UPDATE_STATE_DEFAULTS,
            spec_sha=_h.sha256('# old\n'.encode()).hexdigest())
spec_net('# spec v6\n')
state4, note = m.refresh_spec(seed)
check('T13 it updates devices.md when that is the name in use',
      note == 'device list updated'
      and open(alt, encoding='utf-8').read() == '# spec v6\n', note)
check('T13 and does not create a second file',
      not os.path.exists(SPEC_PATH))

# A failed spec download must not raise or leave a temp file.
clear_specs()
spec_net(error='URLError: offline')
state5, note = m.refresh_spec(dict(m.UPDATE_STATE_DEFAULTS))
check('T13 a failed download is reported, not raised',
      'could not be downloaded' in note, note)
check('T13 and leaves no temporary file',
      not os.path.exists(m.golden_path() + '.new'))
clear_specs()


# ── T14: an update installed from the launcher ENDS the run ───────────────
# The new code is on disk but this interpreter still holds the old one, and
# nothing can reload it. Continuing would run the version just replaced,
# against a real drawing.
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=True,
                  update_interval_days=0.0))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
m.install_update = lambda src: (True, '')
stub_fetch(payload=GOOD, manifest=good_manifest)

alerts = []
vs.AlrtDialog = lambda text: alerts.append(text)
texts = {}
_set = vs.SetItemText


def record(dlg, item, text):
    _set(dlg, item, text)
    texts[item] = text


vs.SetItemText = record


def click_update_then_continue(dlg, handler):
    handler(12255, 0)
    vs.answers = [m.UPDATE_ANSWER_NOW]
    handler(m.lUpdBtn, 0)          # the update installs here
    # Tick real boxes: dialog_overrides is applied by the mock's own
    # RunLayoutDialog, which this replaces, so it would tick nothing.
    vs.SetBooleanItem(dlg, m.lNormChk, True)
    vs.SetBooleanItem(dlg, m.lJobChk, True)
    handler(1, 0)                  # ...and the user ticks tools and continues
    return 1


vs.RunLayoutDialog = click_update_then_continue
picked = m.ask_which_tools()
check('T14 ticking tools after an update runs none of them',
      picked is None, picked)
check('T14 and the user is told CC Tools has closed',
      any('has closed' in a for a in alerts), alerts)
check('T14 and told to pick it again',
      any('menu again' in a for a in alerts), alerts)
check('T14 the status line reported the update too',
      'Updated' in texts.get(m.lSpecTxt, ''), texts.get(m.lSpecTxt))

# Without an update, ticking tools still works exactly as before.
clean()
m.save_prefs(dict(m.PREF_DEFAULTS, check_for_updates=False))
m.save_update_state(dict(m.UPDATE_STATE_DEFAULTS, consent_asked=True))
alerts[:] = []
same = manifest_for(GOOD, version=m.CC_TOOLS_VERSION)
stub_fetch(payload=GOOD, manifest=same)


def click_update_nothing_new(dlg, handler):
    handler(12255, 0)
    handler(m.lUpdBtn, 0)          # checks, finds nothing
    vs.SetBooleanItem(dlg, m.lNormChk, True)
    handler(1, 0)
    return 1


vs.RunLayoutDialog = click_update_nothing_new
vs.dialog_overrides = {}
picked = m.ask_which_tools()
check('T14 a check that finds nothing new does not block the run',
      picked == [m.TOOL_NORMALISE], picked)
check('T14 and says so without an alert',
      not any('has closed' in a for a in alerts), alerts)

vs.SetItemText = _set

clean()
R.report_and_exit()
