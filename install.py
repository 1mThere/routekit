#!/usr/bin/env python3
import argparse
import os
import shutil
import stat
import sys
from pathlib import Path

DEFAULT_PREFIX = Path('/usr/lib/routekit')
BIN = Path('/usr/bin/rk')
ETC = Path('/etc/routekit')
VAR = Path('/var/lib/routekit')

CORE_FILES = [
    '__init__.py',
    '__main__.py',
    'blocklists.py',
    'cli.py',
    'config.py',
    'core.py',
    'domains.py',
    'system.py',
]


def write_executable(path: Path, content: str):
    path.write_text(content, encoding='utf-8')
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_core(source: Path, prefix: Path):
    pkg_src = source / 'routekit'
    pkg_dst = prefix / 'routekit'

    if pkg_dst.exists():
        shutil.rmtree(pkg_dst)

    pkg_dst.mkdir(parents=True, exist_ok=True)

    for name in CORE_FILES:
        shutil.copy2(pkg_src / name, pkg_dst / name)


def install_standard_list(source: Path):
    sys.path.insert(0, str(source))
    from routekit.blocklists import write_default_standard_list
    path = ETC / 'lists' / 'standard.txt'
    try:
        changed, count, errors = write_default_standard_list(path, overwrite=False)
    except Exception as e:
        if not path.exists():
            path.write_text('', encoding='utf-8')
        print(f'standard list: not loaded: {e}')
        return
    if changed:
        print(f'standard list: loaded {count} items')
        for error in errors:
            print(f'standard list source failed: {error}')
    else:
        print('standard list: kept existing')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=str(Path(__file__).resolve().parent))
    parser.add_argument('--prefix', default=str(DEFAULT_PREFIX))
    args = parser.parse_args()

    source = Path(args.source).resolve()
    prefix = Path(args.prefix)

    ETC.mkdir(parents=True, exist_ok=True)
    (ETC / 'lists').mkdir(parents=True, exist_ok=True)
    (VAR / 'modules').mkdir(parents=True, exist_ok=True)

    install_core(source, prefix)
    install_standard_list(source)

    wrapper = f"""#!/bin/sh
export PYTHONPATH='{prefix}'
exec python3 -m routekit "$@"
"""
    write_executable(BIN, wrapper)

    print('installed core: /usr/bin/rk')
    print('config: /etc/routekit/config.json')
    print('modules will be downloaded when enabled')


if __name__ == '__main__':
    main()
