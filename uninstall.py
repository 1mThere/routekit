#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess

paths = [
    Path('/usr/bin/rk'),
    Path('/usr/lib/routekit'),
    Path('/etc/dnsmasq.d/routekit-domain-vpn.conf'),
    Path('/etc/dnsmasq.d/routekit-portal.conf'),
    Path('/usr/share/nftables.d/ruleset-post/40-routekit-domain-vpn.nft'),
    Path('/www-routekit'),
]

for p in paths:
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    else:
        try:
            p.unlink()
        except FileNotFoundError:
            pass

for cmd in (['/etc/init.d/firewall', 'restart'], ['/etc/init.d/dnsmasq', 'restart'], ['/etc/init.d/uhttpd', 'restart']):
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        pass

print('removed runtime files; /etc/routekit is preserved')
