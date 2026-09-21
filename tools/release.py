#!/usr/bin/env python3
"""Publish a release: bump the version and write update.json.

Run from the repository root with the new version:

    python3 tools/release.py 0.9.1 "Fixed the thing" "Added the other thing"

It rewrites CC_TOOLS_VERSION in cc_tools.py, then writes update.json carrying
that version, the file's byte count and its SHA-256. The plug-in verifies all
three before it will install anything, so update.json MUST be regenerated
after any change to cc_tools.py -- a stale checksum means every client
correctly refuses the download.

It refuses to write a manifest for a file that does not compile, so a syntax
error cannot be published to everyone's drafting machine.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAYLOAD = os.path.join(ROOT, 'cc_tools.py')
MANIFEST = os.path.join(ROOT, 'update.json')
VERSION_RE = re.compile(r"(?m)^CC_TOOLS_VERSION = '([^']*)'$")


def fail(message):
    sys.stderr.write('release: {}\n'.format(message))
    raise SystemExit(1)


def main(argv):
    if len(argv) < 2:
        fail('usage: release.py <version> [note ...]')
    version = argv[1].strip()
    if not re.match(r'^\d+\.\d+\.\d+$', version):
        fail('version must look like 1.2.3, got {!r}'.format(version))
    notes = [n.strip() for n in argv[2:] if n.strip()]

    source = open(PAYLOAD, encoding='utf-8').read()
    found = VERSION_RE.search(source)
    if not found:
        fail('could not find CC_TOOLS_VERSION in cc_tools.py')
    if found.group(1) == version:
        fail('cc_tools.py is already at {}'.format(version))

    source = VERSION_RE.sub("CC_TOOLS_VERSION = '{}'".format(version),
                            source, count=1)
    try:
        compile(source, PAYLOAD, 'exec')
    except SyntaxError as err:
        fail('cc_tools.py does not compile (line {}): {}'.format(
            err.lineno, err.msg))

    with open(PAYLOAD, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(source)

    # Hash what will actually be served. raw.githubusercontent.com returns the
    # file verbatim, so this is the same byte string the plug-in downloads.
    data = open(PAYLOAD, 'rb').read()
    manifest = {
        'version': version,
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'min_stub': 1,
        'notes': notes,
    }
    with open(MANIFEST, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(manifest, handle, indent=2)
        handle.write('\n')

    print('cc_tools.py  -> {}'.format(version))
    print('update.json  -> {:,} bytes, sha256 {}'.format(
        manifest['bytes'], manifest['sha256'][:16] + '...'))
    if not notes:
        print('NOTE: no release notes. Users see "No release notes were '
              'published with this version."')
    print('')
    print('Commit BOTH files, then push. Until the push lands, clients '
          'comparing against the old manifest see nothing new.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
