#!/usr/bin/env python3
import argparse
import os
import shutil
import stat
from pathlib import Path

DEFAULT_PREFIX = Path('/usr/lib/routekit')
BIN = Path('/usr/bin/rk')
ETC = Path('/etc/routekit')
VAR = Path('/var/lib/routekit')


def copytree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def write_executable(path: Path, content: str):
    path.write_text(content, encoding='utf-8')
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=str(Path(__file__).resolve().parent))
    parser.add_argument('--prefix', default=str(DEFAULT_PREFIX))
    args = parser.parse_args()

    source = Path(args.source).resolve()
    prefix = Path(args.prefix)

    (ETC / 'modules.d').mkdir(parents=True, exist_ok=True)
    (ETC / 'lists').mkdir(parents=True, exist_ok=True)
    VAR.mkdir(parents=True, exist_ok=True)

    copytree(source / 'routekit', prefix / 'routekit')

    wrapper = f"""#!/bin/sh
export PYTHONPATH='{prefix}'
exec python3 -m routekit "$@"
"""
    write_executable(BIN, wrapper)

    if not (ETC / 'config.json').exists():
        (ETC / 'config.json').write_text('''{
  "lan_iface": "br-lan",
  "dnsmasq_confdir": "/etc/dnsmasq.d",
  "fw4_post_dir": "/usr/share/nftables.d/ruleset-post",
  "modules": {}
}\n''', encoding='utf-8')

    if not (ETC / 'lists' / 'standard.txt').exists():
        (ETC / 'lists' / 'standard.txt').write_text('', encoding='utf-8')

    print('installed: /usr/bin/rk')
    print('config: /etc/routekit/config.json')


if __name__ == '__main__':
    main()
