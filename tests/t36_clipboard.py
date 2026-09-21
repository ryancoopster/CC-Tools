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
vs.SetItemText = lambda dlg, item, text: texts.__setitem__(item, text)


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

clear_spec()
if real is not None:
    sys.modules['subprocess'] = real

R.report_and_exit()
