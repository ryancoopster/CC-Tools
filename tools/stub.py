"""CC Tools loader — paste THIS into the Vectorworks Plug-in Manager.

This is the only part that ever gets pasted, and it never needs pasting
again. It loads the real plug-in from:

    ~/Documents/CC Tools/app/cc_tools.py

which is a plain file the updater can replace in one step. Vectorworks has no
way to reload a plug-in's code in a running session -- there is no API for it,
and its own Plug-in Manager says installing a plug-in needs a restart -- so
keeping the code in a file, rather than inside the .vsm, is what lets an
update take effect on the next menu click instead of the next launch.

SETUP, once:
  1. Make the folder  ~/Documents/CC Tools/app/
  2. Save cc_tools.py into it.
  3. Plug-in Manager > CC Tools > Edit Script, select all, paste this, OK.
"""
import os
import sys
import traceback

import vs

# Bumped only when the stub's contract with the payload changes. update.json
# can carry "min_stub" to refuse an update that would need a newer loader.
CC_TOOLS_STUB_VERSION = 1

PAYLOAD = os.path.expanduser('~/Documents/CC Tools/app/cc_tools.py')
BACKUP = PAYLOAD + '.previous'


def _load(path):
    with open(path, 'r', encoding='utf-8') as handle:
        source = handle.read()
    code = compile(source, path, 'exec')
    namespace = {
        '__name__': '__main__',
        '__file__': path,
        'CC_TOOLS_PAYLOAD': PAYLOAD,
        'CC_TOOLS_STUB_VERSION': CC_TOOLS_STUB_VERSION,
    }
    exec(code, namespace)


def main():
    if not os.path.isfile(PAYLOAD):
        vs.AlrtDialog(
            'CC Tools cannot find its program file.\n\n'
            'Expected it at:\n{}\n\n'
            'Copy cc_tools.py from the CC-Tools repository into that folder, '
            'then run this again.'.format(PAYLOAD))
        return

    try:
        _load(PAYLOAD)
        return
    except Exception:
        first = traceback.format_exc()

    # The live file is broken. An update writes atomically and keeps the
    # version it replaced, so there is very likely a working one right here --
    # try it rather than leaving the user with a dead menu item and no way
    # back from inside Vectorworks.
    if os.path.isfile(BACKUP):
        try:
            _load(BACKUP)
            vs.AlrtDialog(
                'CC Tools failed to load and has fallen back to the previous '
                'version, which is running now.\n\n'
                'The broken file is:\n{}\n\n'
                'Replace it with the working copy at:\n{}\n\n'
                'The error was:\n{}'.format(PAYLOAD, BACKUP, first[-800:]))
            return
        except Exception:
            pass

    vs.AlrtDialog(
        'CC Tools could not start.\n\n{}\n\nThe program file is:\n{}\n\n'
        'Replacing it with a fresh copy from the CC-Tools repository will '
        'fix this.'.format(first[-1200:], PAYLOAD))


main()
