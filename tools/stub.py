"""CC Tools — paste THIS into the Vectorworks Plug-in Manager.

This short script is the whole install. It is the only thing you ever paste,
and it never needs pasting again.

On its first run it offers to fetch CC Tools from its public repository:

    https://github.com/ryancoopster/CC-Tools

and saves it to ~/Documents/CC Tools/app/cc_tools.py. After that it simply
loads that file each time, and CC Tools keeps itself up to date from inside
Vectorworks.

TO INSTALL:
  1. Plug-in Manager > New… > Command, name it "CC Tools", language Python.
  2. Edit Script…, paste this whole file, save.
  3. Tools > Workspaces > Edit Current Workspace > Menus, and drag
     "CC Tools" into a menu.
  4. Pick it from that menu. It will offer to download the rest.

WHY A LOADER AND NOT THE WHOLE PROGRAM: Vectorworks cannot reload a plug-in's
code in a running session -- there is no API for it, and its own Plug-in
Manager says installing a plug-in needs a restart. Keeping the program in a
plain file instead means an update takes effect on the next menu click.

WHAT IT DOWNLOADS, AND HOW IT CHECKS IT: the repository publishes update.json
carrying the expected byte count and SHA-256. Both are verified, and the file
must compile, before anything is written to disk. The two URLs below are
constants -- update.json cannot redirect the download somewhere else.
"""
import os
import sys
import traceback

import vs

# Raised only when this file's contract with the program changes.
CC_TOOLS_STUB_VERSION = 2

REPO = 'ryancoopster/CC-Tools'
BRANCH = 'main'
RAW = 'https://raw.githubusercontent.com/{}/{}/'.format(REPO, BRANCH)
MANIFEST_URL = RAW + 'update.json'
PAYLOAD_URL = RAW + 'cc_tools.py'
SPEC_URL = RAW + 'JOB-SPEC.md'

BASE = os.path.expanduser('~/Documents/CC Tools')
APP_FOLDER = os.path.join(BASE, 'app')
PAYLOAD = os.path.join(APP_FOLDER, 'cc_tools.py')
PREVIOUS = PAYLOAD + '.previous'
SPEC = os.path.join(BASE, 'JOB-SPEC.md')

# Vectorworks' bundled OpenSSL has a compiled-in certificate directory that
# does not exist in the install, so a default SSL context trusts NOTHING and
# every request fails. An explicit bundle is required.
#
# Do NOT "fix" this with vs.InstallCertificate(). Vectorworks' own uploaders
# call it, and what it does is set ssl._create_unverified_context -- it makes
# HTTPS work by turning certificate verification OFF. For a file we are about
# to execute, that is the whole attack.
CA_BUNDLES = ('/etc/ssl/cert.pem', '/usr/local/etc/openssl/cert.pem')


def _context():
    import ssl
    candidates = list(CA_BUNDLES)
    try:
        import certifi
        candidates.append(certifi.where())
    except Exception:
        pass
    for path in candidates:
        try:
            if path and os.path.exists(path):
                context = ssl.create_default_context(cafile=path)
                if context.get_ca_certs():
                    return context
        except Exception:
            continue
    return None


def _fetch(url, timeout):
    """GET over verified HTTPS. Returns (bytes, error)."""
    if not url.startswith('https://'):
        return None, 'refusing a URL that is not HTTPS'
    context = _context()
    if context is None:
        return None, ('no certificate authority bundle was found, so the '
                      'download could not be verified')
    try:
        import urllib.request
        request = urllib.request.Request(
            url, headers={'User-Agent': 'CC-Tools-stub/%d' %
                          CC_TOOLS_STUB_VERSION})
        response = urllib.request.urlopen(request, timeout=timeout,
                                          context=context)
        try:
            return response.read(8 * 1024 * 1024), ''
        finally:
            response.close()
    except Exception as err:
        return None, '%s: %s' % (type(err).__name__, err)


def _write(path, text):
    """Write atomically: a sibling file, flushed, then renamed over the top."""
    temporary = path + '.new'
    with open(temporary, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _record_spec(digest):
    """Note the device list we just wrote, in the program's update state."""
    import json
    path = os.path.join(BASE, 'update_state.json')
    state = {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            state = loaded
    except Exception:
        state = {}
    state['spec_sha'] = digest
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(state, handle, indent=2)
    except Exception:
        pass


def _download():
    """Fetch and verify CC Tools. Returns (ok, message)."""
    import hashlib
    import json

    data, error = _fetch(MANIFEST_URL, 15.0)
    if error:
        return False, 'Could not reach GitHub.\n\n%s' % error
    try:
        manifest = json.loads(data.decode('utf-8'))
    except Exception as err:
        return False, 'The version file could not be read.\n\n%s' % err
    if not isinstance(manifest, dict):
        return False, 'The version file is not in the expected format.'
    expected = str(manifest.get('sha256') or '').strip().lower()
    version = str(manifest.get('version') or 'an unknown version')
    # Refused before the download starts: with no checksum there would be
    # nothing to check the file against, and it is about to be executed.
    if len(expected) != 64:
        return False, ('The version file publishes no usable checksum, so '
                       'the download could not be verified.')

    # A payload can require a newer loader than the one pasted here. Without
    # this check an old loader would download it, run it, and fail somewhere
    # arbitrary inside a program that assumes a contract this file does not
    # honour -- which is a far worse failure than refusing up front.
    try:
        needs = int(manifest.get('min_stub') or 1)
    except (TypeError, ValueError):
        needs = 1
    if needs > CC_TOOLS_STUB_VERSION:
        return False, ('CC Tools %s needs a newer loader than the one '
                       'installed here (it needs %d, this is %d).\n\n'
                       'Copy tools/stub.py from the repository again and '
                       'paste it over this script in the Plug-in Manager:\n'
                       'https://github.com/%s/blob/%s/tools/stub.py'
                       % (version, needs, CC_TOOLS_STUB_VERSION, REPO, BRANCH))

    data, error = _fetch(PAYLOAD_URL, 60.0)
    if error:
        return False, 'Could not download CC Tools.\n\n%s' % error

    size = manifest.get('bytes')
    if isinstance(size, int) and len(data) != size:
        return False, ('The download is incomplete: %d bytes, expected %d.'
                       % (len(data), size))
    if hashlib.sha256(data).hexdigest() != expected:
        return False, ('The download does not match its published checksum, '
                       'so it has not been installed.')
    try:
        source = data.decode('utf-8')
        compile(source, PAYLOAD, 'exec')
    except Exception as err:
        return False, 'The download is not valid Python.\n\n%s' % err

    try:
        os.makedirs(APP_FOLDER, exist_ok=True)
        _write(PAYLOAD, source)
    except Exception as err:
        return False, 'Could not save to:\n%s\n\n%s' % (PAYLOAD, err)

    # The device list. Not code, so it is not checksummed, and failing to get
    # it must not stop CC Tools working -- it only means the curated physical
    # data is missing until the file is put there by hand.
    note = ''
    if not os.path.exists(SPEC):
        spec, spec_error = _fetch(SPEC_URL, 60.0)
        if spec_error:
            note = ('\n\nJOB-SPEC.md could not be downloaded (%s). CC Tools '
                    'works without it, but device dimensions and rack data '
                    'will be missing until you copy it to:\n%s'
                    % (spec_error, SPEC))
        else:
            try:
                os.makedirs(BASE, exist_ok=True)
                _write(SPEC, spec.decode('utf-8'))
                # Record what we wrote, the same way the program's own
                # updater does. Without this it would later see a file it
                # has no hash for, assume the user wrote it, and never
                # refresh the device list again.
                _record_spec(hashlib.sha256(spec).hexdigest())
            except Exception as err:
                note = '\n\nJOB-SPEC.md could not be saved: %s' % err

    return True, 'CC Tools %s installed to:\n%s%s' % (version, PAYLOAD, note)


def _load(path):
    with open(path, 'r', encoding='utf-8') as handle:
        source = handle.read()
    exec(compile(source, path, 'exec'), {
        '__name__': '__main__',
        '__file__': path,
        'CC_TOOLS_PAYLOAD': PAYLOAD,
        'CC_TOOLS_STUB_VERSION': CC_TOOLS_STUB_VERSION,
    })


def main():
    if not os.path.isfile(PAYLOAD):
        asked = vs.AlertQuestion(
            'CC Tools is not installed yet. Download it now?',
            'It will be downloaded from:\n%s\n\nand saved to:\n%s\n\n'
            'The download is checked against the checksum published with it '
            'before anything is saved. Nothing else on your computer is '
            'touched, and no information about you or your drawings is sent.'
            % (PAYLOAD_URL, PAYLOAD),
            0, 'Download', 'Cancel', '', '')
        if asked != 1:
            return
        ok, message = _download()
        if not ok:
            vs.AlrtDialog('CC Tools could not be installed.\n\n%s' % message)
            return
        vs.AlrtDialog(message)

    try:
        _load(PAYLOAD)
        return
    except Exception:
        first = traceback.format_exc()

    # The program file is broken. An update writes atomically and keeps the
    # version it replaced, so there is very likely a working one right here --
    # run that rather than leaving a dead menu item and no way back.
    if os.path.isfile(PREVIOUS):
        try:
            _load(PREVIOUS)
            vs.AlrtDialog(
                'CC Tools failed to start and has fallen back to the previous '
                'version, which is running now.\n\nThe broken file is:\n%s\n\n'
                'The error was:\n%s' % (PAYLOAD, first[-700:]))
            return
        except Exception:
            pass

    vs.AlrtDialog(
        'CC Tools could not start.\n\n%s\n\nIts program file is:\n%s\n\n'
        'Deleting that file and running CC Tools again will download a fresh '
        'copy.' % (first[-1000:], PAYLOAD))


main()
