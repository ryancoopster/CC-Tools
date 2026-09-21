"""The launcher's 'Copy JOB-SPEC.md for Claude' button.

VectorScript has no clipboard routine, so this shells out. The platform choice
is a pure function precisely so it can be checked here without a Windows box,
and the subprocess call is faked so a test run never touches the real
clipboard.
"""
import os
import sys
import types

from harness import Doc, Results, load, dev

R = Results()
check = R.check
m, vs = load(Doc([[dev('x')]]))

SPEC = os.path.join(m.BASE_FOLDER, 'JOB-SPEC.md')


def clear_spec():
    for name in m.GOLDEN_FILES:
        path = os.path.join(m.BASE_FOLDER, name)
        if os.path.exists(path):
            os.remove(path)


class FakeProc(object):
    def __init__(self, rc=0, err=b''):
        self.returncode = rc
        self._err = err
        self.sent = None

    def communicate(self, payload):
        self.sent = payload
        return (b'', self._err)


def fake_subprocess(rc=0, err=b'', explode=None):
    """A stand-in subprocess module. Records what was run."""
    calls = []
    mod = types.ModuleType('subprocess')
    mod.PIPE = -1

    def Popen(argv, **kwargs):
        calls.append(argv)
        if explode:
            raise explode
        return FakeProc(rc, err)

    mod.Popen = Popen
    return mod, calls


# ── T1: which command each platform gets ──────────────────────────────────
mac = m.clipboard_commands('hello', 'darwin', 'posix')
check('T1 macOS uses pbcopy', mac[0][0] == ['pbcopy'], mac[0][0])
check('T1 macOS sends UTF-8', mac[0][1] == b'hello')
check('T1 macOS tries exactly one command', len(mac) == 1, len(mac))

win = m.clipboard_commands('hello', 'win32', 'nt')
check('T1 Windows tries PowerShell first', win[0][0][0] == 'powershell', win[0][0])
check('T1 Windows falls back to clip', win[1][0] == ['clip'], win[1][0])
check('T1 the clip fallback is UTF-16LE, which is what clip reads',
      win[1][1] == 'hello'.encode('utf-16-le'))
check('T1 PowerShell gets UTF-8', win[0][1] == b'hello')

nix = m.clipboard_commands('hello', 'linux', 'posix')
check('T1 Linux tries xclip then xsel',
      [c[0][0] for c in nix] == ['xclip', 'xsel'], [c[0][0] for c in nix])

# An em-dash survives the encoding rather than raising.
dashed = m.clipboard_commands('a — b', 'darwin', 'posix')
check('T1 non-ASCII encodes without raising',
      dashed[0][1] == 'a — b'.encode('utf-8'))


# ── T2: copy_to_clipboard success and failure ─────────────────────────────
real = sys.modules.get('subprocess')
fake, calls = fake_subprocess()
sys.modules['subprocess'] = fake
ok, detail = m.copy_to_clipboard('payload')
check('T2 a clean exit reports success', ok is True, (ok, detail))
check('T2 it names the command it used', detail in ('pbcopy', 'xclip'), detail)
check('T2 it actually ran something', len(calls) == 1, calls)

fake, calls = fake_subprocess(rc=1, err=b'pbcopy: broken pipe')
sys.modules['subprocess'] = fake
ok, detail = m.copy_to_clipboard('payload')
check('T2 a non-zero exit is a failure', ok is False, (ok, detail))
check('T2 the error text is passed back', 'broken pipe' in detail, detail)

fake, calls = fake_subprocess(explode=OSError('no such file'))
sys.modules['subprocess'] = fake
ok, detail = m.copy_to_clipboard('payload')
check('T2 a missing binary is a failure, not a crash', ok is False, (ok, detail))
check('T2 and it says why', 'no such file' in detail, detail)

# Every command failing must still return, not raise.
fake, calls = fake_subprocess(rc=1)
sys.modules['subprocess'] = fake
ok, detail = m.copy_to_clipboard('payload')
check('T2 exhausting every command returns a reason', ok is False and detail, detail)


# ── T3: copy_job_spec reads the same file the device list does ────────────
clear_spec()
fake, calls = fake_subprocess()          # fresh, so `calls` means THIS call
sys.modules['subprocess'] = fake
status = m.copy_job_spec()
check('T3 a missing spec is reported, not copied',
      'not in' in status and 'devices.md' in status, status)
check('T3 and nothing was sent to the clipboard', len(calls) == 0, calls)

with open(SPEC, 'w', encoding='utf-8') as f:
    f.write('')
status = m.copy_job_spec()
check('T3 an empty spec is refused', 'empty' in status.lower(), status)

BODY = '# ConnectCAD schematic job\n\nSome spec — with an em-dash.\n'
with open(SPEC, 'w', encoding='utf-8') as f:
    f.write(BODY)
fake, calls = fake_subprocess()
sys.modules['subprocess'] = fake
status = m.copy_job_spec()
check('T3 a real spec is copied', 'Copied' in status, status)
check('T3 the status names the file', 'JOB-SPEC.md' in status, status)
check('T3 the status gives the size', str(len(BODY)) in status.replace(',', ''),
      status)
check('T3 the whole file went to the clipboard, not a truncation',
      calls and len(calls) == 1, calls)

# The button and the device-list reader must never disagree about the file.
check('T3 it reads exactly golden_path()',
      m.golden_path() == SPEC, (m.golden_path(), SPEC))

# Saved under the other accepted name, it still works.
os.remove(SPEC)
alt = os.path.join(m.BASE_FOLDER, 'devices.md')
with open(alt, 'w', encoding='utf-8') as f:
    f.write(BODY)
fake, calls = fake_subprocess()
sys.modules['subprocess'] = fake
status = m.copy_job_spec()
check('T3 the alternate filename is accepted too',
      'Copied' in status and 'devices.md' in status, status)

# A clipboard failure must still tell the user where the file is.
fake, calls = fake_subprocess(rc=1, err=b'nope')
sys.modules['subprocess'] = fake
status = m.copy_job_spec()
check('T3 a clipboard failure names the path so the work is not lost',
      m.BASE_FOLDER in status and 'Could not' in status, status)


# ── T4: the launcher wiring ───────────────────────────────────────────────
with open(alt, 'w', encoding='utf-8') as f:
    f.write(BODY)
fake, calls = fake_subprocess()
sys.modules['subprocess'] = fake

texts = {}
# Wrap rather than replace: the mock's width guard must still run, or this
# test would pass on a status line that is cut off on screen.
_real_set_item_text = vs.SetItemText


def recording_set_item_text(dlg, item, text):
    _real_set_item_text(dlg, item, text)
    texts[item] = text


vs.SetItemText = recording_set_item_text


def run_clicking_copy(dlg, handler):
    handler(12255, 0)          # setup
    handler(m.lSpecBtn, 0)     # the user clicks Copy
    handler(1, 0)              # then OK, having ticked nothing
    return 1


vs.RunLayoutDialog = run_clicking_copy
picked = m.ask_which_tools()

check('T4 clicking Copy writes a status line',
      m.lSpecTxt in texts, list(texts))
check('T4 and the status says it copied',
      'Copied' in texts.get(m.lSpecTxt, ''), texts.get(m.lSpecTxt))
check('T4 clicking Copy selects no tool', picked == [], picked)
check('T4 the button is not one of the tool checkboxes',
      m.lSpecBtn not in (m.lNormChk, m.lMatchChk, m.lSpellChk, m.lSearchChk,
                         m.lReplaceChk, m.lReconChk, m.lJobChk, m.lPrefsChk,
                         m.lPromptChk, m.lDumpChk, m.lRefChk, m.lProbeChk))
check('T4 its ids do not collide with any other launcher item',
      len({m.lSpecBtn, m.lSpecTxt, m.lToolLbl, m.lSetupLbl, m.lOrderTxt,
           m.lHintTxt, m.lNormChk, m.lMatchChk, m.lSpellChk, m.lSearchChk,
           m.lReplaceChk, m.lReconChk, m.lJobChk, m.lPrefsChk, m.lPromptChk,
           m.lDumpChk, m.lRefChk, m.lProbeChk}) == 18)


# ── T5: status text must fit the box it is drawn in ──────────────────────
# A layout dialog sizes a static text item when it is CREATED and never grows
# it. The copy confirmation was 101 characters in a box built for 78, so the
# user saw "Paste it into a new" and nothing after it.
W = m.STATUS_WIDTH
L = m.STATUS_LINES

CUT_OFF = ('Copied JOB-SPEC.md (33,634 characters). Paste it into a new '
           'Claude chat, then describe the schematic.')
wrapped = m.wrap_status(CUT_OFF)
check('T5 the message that was cut off now fits',
      all(len(line) <= W for line in wrapped.split('\n')),
      [len(l) for l in wrapped.split('\n')])
check('T5 and none of its words are lost',
      ''.join(wrapped.split()) == ''.join(CUT_OFF.split()),
      wrapped)
check('T5 every status line is exactly the reserved width',
      all(len(line) == W for line in wrapped.split('\n')))
check('T5 and exactly the reserved number of lines',
      len(wrapped.split('\n')) == L, wrapped.count('\n') + 1)

# The item is created with a placeholder; it must reserve the full width, or
# the box is too small before a single message is written.
created = m.wrap_status('short')
check('T5 the creation placeholder reserves full width and height',
      len(created.split('\n')) == L
      and all(len(line) == W for line in created.split('\n')))

# An unbounded path or error string must not overflow.
long_path = '/Users/someone/Documents/CC Tools/app/' + 'x' * 200 + '.py'
wrapped = m.wrap_status('Could not reach the clipboard. The file is at '
                        + long_path)
check('T5 a path with no spaces is hard-split rather than overflowing',
      all(len(line) <= W for line in wrapped.split('\n')),
      [len(l) for l in wrapped.split('\n')])
check('T5 and the line count is still capped',
      len(wrapped.split('\n')) == L)
check('T5 a message too long to show is marked as cut, not left looking whole',
      wrapped.split('\n')[-1].rstrip().endswith('...'),
      repr(wrapped.split('\n')[-1][-12:]))

# Multi-line messages (the updater writes these) must survive.
multi = m.wrap_status('Updated to 0.9.3.\n\nPick CC Tools from the menu '
                      'again to use it.')
check('T5 a multi-line message keeps its words',
      'Updated' in multi and 'menu' in multi, multi)
check('T5 and still fits', all(len(l) <= W for l in multi.split('\n')))

check('T5 empty text still reserves the box',
      len(m.wrap_status('').split('\n')) == L
      and all(len(l) == W for l in m.wrap_status('').split('\n')))

# Every message the launcher can put in that line must fit in the box.
for message in [m.copy_job_spec(),
                'CC Tools 0.9.3 is the latest version.',
                'No update information was available.',
                'Could not check for updates: URLError: [Errno 8] nodename '
                'nor servname provided, or not known']:
    fitted = m.wrap_status(message)
    check('T5 fits: %s' % message[:34],
          all(len(line) == W for line in fitted.split('\n'))
          and len(fitted.split('\n')) == L)


# ── T6: the mock itself catches this class, or the tests above prove little ──
# mockvs used to discard the creation text, so a fix and a non-fix looked
# identical to the suite. These assert the new guard actually fires.
vs.SetItemText = _real_set_item_text      # the guarded one, not the recorder
caught = ''
try:
    vs.CreateStaticText(1, 9901, 'x' * 20, -1)
    vs.SetItemText(1, 9901, 'y' * 21)
except AssertionError as err:
    caught = str(err)
check('T6 writing more text than the box was built for now fails a test',
      'cut off' in caught, caught or 'nothing raised')

caught = ''
try:
    vs.CreateStaticText(1, 9902, 'x' * 20, -1)
    vs.SetItemText(1, 9902, 'y' * 20)
except AssertionError as err:
    caught = str(err)
check('T6 and text that fits does not', caught == '', caught)

caught = ''
try:
    vs.CreatePullDownMenu(1, 9903, 10)
    vs.AddChoice(1, 9903, 'a label far too long', 0)
except AssertionError as err:
    caught = str(err)
check('T6 a menu label wider than its menu fails a test',
      'clipped' in caught, caught or 'nothing raised')

caught = ''
try:
    vs.CreatePullDownMenu(1, 9904, 30)
    vs.AddChoice(1, 9904, 'a label that fits', 0)
except AssertionError as err:
    caught = str(err)
check('T6 and a label that fits does not', caught == '', caught)

# The real launcher must survive its own guard, with a real message in place.
check('T6 the launcher status line holds every message it can show',
      all(len(line) <= m.STATUS_WIDTH
          for msg in [m.copy_job_spec(), 'CC Tools 0.9.4 is the latest version.']
          for line in m.wrap_status(msg).split('\n')))

clear_spec()
if real is not None:
    sys.modules['subprocess'] = real

R.report_and_exit()
