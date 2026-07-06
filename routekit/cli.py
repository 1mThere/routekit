import argparse
import subprocess
from pathlib import Path

from .core import Core, MODULES
from .domains import normalize_many, read_list, write_list
from .config import CONFIG_PATH


def cmd_init(args):
    c = Core()
    c.init()
    print(f'initialized: {CONFIG_PATH}')


def cmd_module(args):
    c = Core()
    if args.module_cmd == 'list':
        for mod in c.modules():
            cfg = mod.cfg()
            print(f'{mod.name}\t{"enabled" if cfg.get("enabled") else "disabled"}')
    elif args.module_cmd == 'enable':
        c.enable_module(args.name)
        print(f'enabled: {args.name}')
    elif args.module_cmd == 'disable':
        c.disable_module(args.name)
        print(f'disabled: {args.name}')
    elif args.module_cmd == 'set':
        c.set_module_value(args.name, args.key, args.value)
        print(f'set: {args.name}.{args.key}={args.value}')
    elif args.module_cmd == 'status':
        if args.name not in MODULES:
            raise SystemExit(f'unknown module: {args.name}')
        mod = MODULES[args.name](c)
        for k, v in mod.status().items():
            print(f'{k}: {v}')


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


def cmd_self(args):
    if args.self_cmd == 'update':
        repo = Path('/opt/routekit')
        if not (repo / '.git').exists():
            raise SystemExit('self update needs git checkout at /opt/routekit')
        subprocess.run(['git', '-C', str(repo), 'pull', '--ff-only'], check=True)
        subprocess.run(['python3', str(repo / 'install.py'), '--source', str(repo)], check=True)


def build_parser():
    p = argparse.ArgumentParser(prog='rk')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('init')
    s.set_defaults(func=cmd_init)

    s = sub.add_parser('apply')
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser('doctor')
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser('module')
    msub = s.add_subparsers(dest='module_cmd', required=True)
    x = msub.add_parser('list')
    x.set_defaults(func=cmd_module)
    x = msub.add_parser('enable')
    x.add_argument('name')
    x.set_defaults(func=cmd_module)
    x = msub.add_parser('disable')
    x.add_argument('name')
    x.set_defaults(func=cmd_module)
    x = msub.add_parser('set')
    x.add_argument('name')
    x.add_argument('key')
    x.add_argument('value')
    x.set_defaults(func=cmd_module)
    x = msub.add_parser('status')
    x.add_argument('name')
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
    x.set_defaults(func=cmd_self)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
