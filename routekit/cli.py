import argparse
import ipaddress
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import CONFIG_PATH
from .core import Core
from .domains import normalize_domain, normalize_many, read_list, write_list

ARCHIVE_URL = 'https://github.com/1mThere/routekit/archive/refs/heads/main.tar.gz'


def cmd_init(args):
    c = Core()
    c.init()
    print(f'initialized: {CONFIG_PATH}')


def cmd_enable(args):
    Core().enable_module(args.name)
    print(f'enabled: {args.name}')


def cmd_disable(args):
    Core().disable_module(args.name)
    print(f'disabled: {args.name}')


def cmd_modules(args):
    c = Core()
    if args.modules_cmd == 'list':
        enabled = set(c.enabled_names())
        for name, reg in sorted(c.registry().items()):
            status = 'enabled' if name in enabled else 'disabled'
            impl = 'ok' if reg.get('implemented', True) else 'not-implemented'
            deps = ','.join(reg.get('deps', [])) or '-'
            downloaded = 'downloaded' if c.module_path(name).exists() else 'not-downloaded'
            print(f'{name}\t{status}\t{impl}\tdeps={deps}\t{downloaded}')
    elif args.modules_cmd == 'set':
        c.set_module_value(args.name, args.key, args.value)
        print(f'set: {args.name}.{args.key}={args.value}')
    elif args.modules_cmd == 'status':
        if args.name not in c.enabled_names():
            raise SystemExit(f'module is not enabled: {args.name}')
        mod = c.load_module(args.name)
        for k, v in mod.status().items():
            print(f'{k}: {v}')
    elif args.modules_cmd == 'update':
        if args.name:
            c.refresh_module(args.name)
        else:
            c.refresh_modules(enabled_only=not args.all)
        print('modules updated')


def list_path():
    return Path('/etc/routekit/lists/standard.txt')


def _normalize_stlist(items):
    out = set()
    for item in items:
        for part in str(item).replace(',', ' ').split():
            value = part.strip().lower()
            if not value or value.startswith('#'):
                continue
            try:
                net = ipaddress.ip_network(value, strict=False)
                if net.version == 4:
                    if net.prefixlen == 32:
                        out.add(str(net.network_address))
                    else:
                        out.add(str(net))
                    continue
            except Exception:
                pass
            domain = normalize_domain(value)
            if domain:
                out.add(domain)
    return sorted(out)


def _read_stlist(path):
    path = Path(path)
    if not path.exists():
        return []
    return _normalize_stlist(path.read_text(encoding='utf-8', errors='ignore').splitlines())


def _write_stlist(path, items):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(set(items))
    path.write_text('\n'.join(items) + ('\n' if items else ''), encoding='utf-8')


def cmd_vpn(args):
    p = list_path()
    current = _read_stlist(p)
    if args.vpn_cmd == 'stlist':
        if args.stlist_cmd == 'list':
            for i, item in enumerate(current, 1):
                print(f'{i:6d}  {item}')
        elif args.stlist_cmd == 'add':
            items = _normalize_stlist(args.items)
            _write_stlist(p, sorted(set(current) | set(items)))
            print(f'added: {len(items)}')
        elif args.stlist_cmd == 'del':
            items = set(_normalize_stlist(args.items))
            _write_stlist(p, [x for x in current if x not in items])
            print(f'deleted: {len(items)}')
        elif args.stlist_cmd == 'replace':
            items = _normalize_stlist(args.items)
            _write_stlist(p, items)
            print(f'replaced: {len(items)}')


def cmd_domain(args):
    p = list_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    current = read_list(p)
    if args.domain_cmd == 'list':
        for i, d in enumerate(current, 1):
            print(f'{i:6d}  {d}')
    elif args.domain_cmd == 'add':
        domains = normalize_many(args.domains)
        write_list(p, sorted(set(current) | set(domains)))
        print(f'added: {len(domains)}')
    elif args.domain_cmd == 'del':
        domains = set(normalize_many(args.domains))
        write_list(p, [d for d in current if d not in domains])
        print(f'deleted: {len(domains)}')
    elif args.domain_cmd == 'replace':
        domains = normalize_many(args.domains)
        write_list(p, domains)
        print(f'replaced: {len(domains)}')


def cmd_apply(args):
    Core().apply()
    print('applied')


def cmd_doctor(args):
    Core().doctor()


def _run(argv, label=None, check=True):
    p = subprocess.run(argv, text=True)
    if check and p.returncode != 0:
        name = label or argv[0]
        raise SystemExit(f'{name} failed: exit code {p.returncode}')
    return p


def _download_archive(dst):
    _run([
        'curl',
        '-fsSL',
        '--retry', '3',
        '--retry-delay', '1',
        '--retry-all-errors',
        '--connect-timeout', '8',
        '--max-time', '60',
        '--speed-time', '10',
        '--speed-limit', '1024',
        ARCHIVE_URL,
        '-o', str(dst),
    ], 'download update')


def _install_from_archive():
    with tempfile.TemporaryDirectory(prefix='routekit-update-') as d:
        root = Path(d)
        archive = root / 'routekit.tar.gz'
        _download_archive(archive)
        _run(['tar', '-xzf', str(archive), '-C', str(root)], 'unpack update')
        source = root / 'routekit-main'
        _run(['python3', str(source / 'install.py'), '--source', str(source)], 'install update')


def _install_from_git(repo):
    _run(['git', '-C', str(repo), 'pull', '--ff-only'], 'git update')
    _run(['python3', str(repo / 'install.py'), '--source', str(repo)], 'install update')


def cmd_update(args):
    repo = Path('/opt/routekit')
    if (repo / '.git').exists():
        _install_from_git(repo)
    else:
        _install_from_archive()
    _run(['/usr/bin/rk', 'modules', 'update'], 'modules update')
    if args.apply:
        _run(['/usr/bin/rk', 'apply'], 'apply')
    print('routekit updated')


def _rm(path):
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _restore_uhttpd():
    backup = Path('/etc/routekit/backups/uhttpd.before-webportal')
    if backup.exists():
        shutil.copy2(backup, '/etc/config/uhttpd')
        return
    _run(['uci', '-q', 'delete', 'uhttpd.routekit'], check=False)
    _run(['uci', 'commit', 'uhttpd'], check=False)


def cmd_uninstall(args):
    c = Core()
    try:
        c.rescue()
    except Exception as e:
        print(f'rescue failed: {e}')

    _run(['uci', '-q', 'delete', 'uhttpd.routekit'], check=False)
    _restore_uhttpd()

    for p in [
        '/www-routekit',
        '/etc/dnsmasq.d/routekit-webportal.conf',
        '/etc/dnsmasq.d/routekit-vpn.conf',
        '/etc/dnsmasq.d/routekit-domain-vpn.conf',
        '/usr/share/nftables.d/ruleset-post/40-routekit-vpn.nft',
        '/usr/share/nftables.d/ruleset-post/40-routekit-domain-vpn.nft',
        '/var/lib/routekit',
        '/usr/lib/routekit',
        '/etc/routekit',
        '/usr/bin/rk',
    ]:
        _rm(p)

    for svc in ('firewall', 'dnsmasq', 'uhttpd'):
        _run([f'/etc/init.d/{svc}', 'restart'], check=False)
    print('routekit uninstalled')


def build_parser():
    p = argparse.ArgumentParser(prog='rk')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('init')
    s.set_defaults(func=cmd_init)

    s = sub.add_parser('apply')
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser('doctor')
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser('update')
    s.add_argument('--apply', action='store_true')
    s.add_argument('--no-apply', action='store_true')
    s.set_defaults(func=cmd_update)

    s = sub.add_parser('uninstall')
    s.set_defaults(func=cmd_uninstall)

    s = sub.add_parser('enable')
    s.add_argument('name')
    s.set_defaults(func=cmd_enable)

    s = sub.add_parser('disable')
    s.add_argument('name')
    s.set_defaults(func=cmd_disable)

    s = sub.add_parser('modules')
    msub = s.add_subparsers(dest='modules_cmd', required=True)
    x = msub.add_parser('list')
    x.set_defaults(func=cmd_modules)
    x = msub.add_parser('set')
    x.add_argument('name')
    x.add_argument('key')
    x.add_argument('value')
    x.set_defaults(func=cmd_modules)
    x = msub.add_parser('status')
    x.add_argument('name')
    x.set_defaults(func=cmd_modules)
    x = msub.add_parser('update')
    x.add_argument('name', nargs='?')
    x.add_argument('--all', action='store_true')
    x.set_defaults(func=cmd_modules)

    s = sub.add_parser('vpn')
    vsub = s.add_subparsers(dest='vpn_cmd', required=True)
    x = vsub.add_parser('stlist')
    st = x.add_subparsers(dest='stlist_cmd', required=True)
    y = st.add_parser('list')
    y.set_defaults(func=cmd_vpn)
    y = st.add_parser('add')
    y.add_argument('items', nargs='+')
    y.set_defaults(func=cmd_vpn)
    y = st.add_parser('del')
    y.add_argument('items', nargs='+')
    y.set_defaults(func=cmd_vpn)
    y = st.add_parser('replace')
    y.add_argument('items', nargs='+')
    y.set_defaults(func=cmd_vpn)

    s = sub.add_parser('domain')
    dsub = s.add_subparsers(dest='domain_cmd', required=True)
    x = dsub.add_parser('list')
    x.set_defaults(func=cmd_domain)
    x = dsub.add_parser('add')
    x.add_argument('domains', nargs='+')
    x.set_defaults(func=cmd_domain)
    x = dsub.add_parser('del')
    x.add_argument('domains', nargs='+')
    x.set_defaults(func=cmd_domain)
    x = dsub.add_parser('replace')
    x.add_argument('domains', nargs='+')
    x.set_defaults(func=cmd_domain)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
