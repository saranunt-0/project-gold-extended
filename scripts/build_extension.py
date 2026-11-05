# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Package ``gold_extended/`` as an installable Blender extension zip.

Preferred (official tool, validates the manifest):

    blender --command extension build --source-dir gold_extended --output-dir dist

Fallback without Blender (same layout: manifest at the zip root):

    python scripts/build_extension.py [--out dist]
"""

import argparse
import os
import tomllib
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'gold_extended')
EXCLUDE_DIRS = {'__pycache__', '.git'}
EXCLUDE_EXT = {'.pyc', '.pyo', '.blend1'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'))
    args = ap.parse_args()
    with open(os.path.join(SRC, 'blender_manifest.toml'), 'rb') as f:
        manifest = tomllib.load(f)
    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, f"{manifest['id']}-{manifest['version']}.zip")
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(SRC):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
            for fn in sorted(files):
                if os.path.splitext(fn)[1] in EXCLUDE_EXT:
                    continue
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, SRC))
    print(out)


if __name__ == '__main__':
    main()
