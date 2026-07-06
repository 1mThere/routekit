import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import CONFIG_PATH
from .core import Core
from .domains import normalize_many, read_list, write_list

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


def cmd_module(args):
    c = Core()
    if args.module_cmd == 'list':
        enabled = set(c.enabled_names())
        for name, reg in sorted(c.registry().items()):
            status = 'enabled' if name in enabled else 'disabled'
            impl = 'ok' if reg.get('implemented', True) else 'not-implemented'
            deps = ','.join(reg.get('deps', [])) or '-'
            downloaded = 'downloaded' if c.module_path(name).exists() else 'not-downloaded'
            print(f'{name}\t{status}\t{impl}\tdeps={deps}\t{downloaded}')
    elif args.module_cmd == 'set':
        c.set_module_value(args.name, args.key, args.value)
        print(f'set: {args.name}.{args.key}={args.value}')
    elif args.module_cmd == 'status':
        if args.name not in c.enabled_names():
            raise SystemExit(f'module is not enabled: {args.name}')
        mod = c.load_module(args.name)
        for k, v in mod.status().items():
            print(f'{k}: {v}')
    elif args.module_cmd == 'refresh':
        if args.name:
            c.refresh_module(args.name)
        else:
            c.refresh_modules(enabled_only=not args.all)
        print('modules refreshed')


def list_path():
    return Path('/etc/routekit/lists/standard.txt')


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


def _run(argv):
    subprocess.run(argv, check=True)


def _download_archive(dst):
    _run(['curl', '-fL', '--connect-timeout', '20', '--max-time', '240', ARCHIVE_URL, '-o', str(dst)])


def _install_from_archive():
    with tempfile.TemporaryDirectory(prefix='routekit-update-') as d:
        root = Path(d)
        archive = root / 'routekit.tar.gz'
        _download_archive(archive)
        _run(['tar', '-xzf', str(archive), '-C', str(root)])
        source = root / 'routekit-main'
        _run(['python3', str(source / 'install.py'), '--source', str(source)])


def _install_from_git(repo):
    _run(['git', '-C', str(repo), 'pull', '--ff-only'])
    _run(['python3', str(repo / 'install.py'), '--source', str(repo)])


def cmd_self(args):
    if args.self_cmd == 'update':
        repo = Path('/opt/routekit')
        if (repo / '.git').exists():
            _install_from_git(repo)
        else:
            _install_from_archive()
        _run(['/usr/bin/rk', 'module', 'refresh'])
        if not args.no_apply:
            _run(['/usr/bin/rk', 'apply'])
        print('routekit updated')


def build_parser():
    p = argparse.ArgumentParser(prog='rk')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('init')
    s.set_defaults(func=cmd_init)

    s = sub.add_parser('apply')
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser('doctor')
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser('enable')
    s.add_argument('name')
    s.set_defaults(func=cmd_enable)

    s = sub.add_parser('disable')
    s.add_argument('name')
    s.set_defaults(func=cmd_disable)

    s = sub.add_parser('module')
    msub = s.add_subparsers(dest='module_cmd', required=True)
    x = msub.add_parser('list')
    x.set_defaults(func=cmd_module)
    x = msub.add_parser('set')
    x.add_argument('name')
    x.add_argument('key')
    x.add_argument('value')
    x.set_defaults(func=cmd_module)
    x = msub.add_parser('status')
    x.add_argument('name')
    x.set_defaults(func=cmd_module)
    x = msub.add_parser('refresh')
    x.add_argument('name', nargs='?')
    x.add_argument('--all', action='store_true')
    x.set_defaults(func=cmd_module)

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

    s = sub.add_parser('self')
    ss = s.add_subparsers(dest='self_cmd', required=True)
    x = ss.add_parser('update')
    x.add_argument('--no-apply', action='store_true')
    x.set_defaults(func=cmd_self)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
