import json
import shutil
import time
import urllib.request
from pathlib import Path
from subprocess import run, PIPE

PROVIDER = 'openvpn'
PRIORITY = 30
DEFAULTS = {
    'interface': 'vpnclient',
    'config_path': '/etc/openvpn/routekit_openvpn.ovpn',
    'device': 'auto',
    'table_id': 1001,
    'table_name': 'rk_openvpn',
    'mark': '0x00520000',
    'mark_mask': '0x00ff0000',
    'priority': 25000,
    'wait_seconds': 20,
}


def _out(argv):
    p = run(argv, text=True, stdout=PIPE, stderr=PIPE)
    if p.returncode != 0:
        return ''
    return p.stdout.strip()


def _run(argv):
    return run(argv, text=True, stdout=PIPE, stderr=PIPE)


def _ask(prompt, default=''):
    suffix = f' [{default}]' if default else ''
    return input(f'{prompt}{suffix}: ').strip().strip('"\'') or default


def _normalize_source(src):
    src = (src or '').strip().strip('"\'')
    bad_prefixes = ('rk apply', 'rk enable openvpn')
    for prefix in bad_prefixes:
        if src.startswith(prefix):
            src = src[len(prefix):].strip()
    if src.startswith('apply/'):
        src = src[5:]
    if src.startswith('rk apply/'):
        src = src[8:]
    return src


def _dev_exists(dev):
    if not dev:
        return False
    return run(['ip', 'link', 'show', 'dev', dev], text=True, stdout=PIPE, stderr=PIPE).returncode == 0


def _first_tunnel_dev():
    links = _out(['ip', '-o', 'link', 'show']).splitlines()
    for line in links:
        name = line.split(':', 2)[1].strip().split('@', 1)[0]
        if name.startswith('tun') or name.startswith('tap') or name.startswith('ovpn') or name.startswith('wg'):
            return name
    return ''


def _config_dev(path):
    p = Path(path or '')
    if not p.exists():
        return ''
    for raw in p.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == 'dev':
            return parts[1]
    return ''


def _expected_dev(cfg):
    manual = cfg.get('device')
    if manual and manual != 'auto':
        return manual
    dev = _config_dev(cfg.get('config_path'))
    if dev:
        return dev
    return _first_tunnel_dev()


def _ready_dev(cfg):
    dev = _expected_dev(cfg)
    if _dev_exists(dev):
        return dev
    dev = _first_tunnel_dev()
    if _dev_exists(dev):
        return dev
    return ''


def _wait_ready_dev(cfg):
    timeout = int(cfg.get('wait_seconds', 20))
    for _ in range(max(timeout, 1)):
        dev = _ready_dev(cfg)
        if dev:
            return dev
        time.sleep(1)
    return ''


def enable(core, cfg):
    src = _normalize_source(_ask('OpenVPN config file path or URL', ''))
    if src:
        dst = Path(cfg.get('config_path') or '/etc/openvpn/routekit_openvpn.ovpn')
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.startswith('http://') or src.startswith('https://'):
            try:
                with urllib.request.urlopen(src, timeout=60) as r:
                    dst.write_bytes(r.read())
            except Exception as e:
                raise SystemExit(f'cannot download OpenVPN config: {e}')
        else:
            source = Path(src)
            if not source.exists():
                raise SystemExit(f'OpenVPN config not found: {source}')
            if source.resolve() != dst.resolve():
                shutil.copy2(source, dst)
        cfg['config_path'] = str(dst)

    cfg['interface'] = _ask('OpenWrt network interface', cfg.get('interface', 'vpnclient'))
    cfg['device'] = _ask('VPN device, or auto', cfg.get('device', 'auto'))


def render(core, cfg):
    return []


def apply(core, cfg):
    config_path = cfg.get('config_path')
    iface = cfg.get('interface', 'vpnclient')

    if config_path and Path(config_path).exists():
        _run(['uci', '-q', 'delete', 'openvpn.routekit_openvpn'])
        _run(['uci', 'set', 'openvpn.routekit_openvpn=openvpn'])
        _run(['uci', 'set', 'openvpn.routekit_openvpn.enabled=1'])
        _run(['uci', 'set', f'openvpn.routekit_openvpn.config={config_path}'])
        _run(['uci', 'commit', 'openvpn'])
        _run(['/etc/init.d/openvpn', 'enable'])
        _run(['/etc/init.d/openvpn', 'restart'])

    table_id = str(cfg['table_id'])
    table_name = str(cfg['table_name'])
    mark = str(cfg['mark'])
    mask = str(cfg['mark_mask'])
    prio = str(cfg['priority'])

    rt = Path('/etc/iproute2/rt_tables')
    current = rt.read_text(encoding='utf-8', errors='ignore') if rt.exists() else ''
    if f'{table_id} {table_name}' not in current:
        with rt.open('a', encoding='utf-8') as f:
            f.write(f'{table_id} {table_name}\n')

    dev = _wait_ready_dev(cfg)
    if not dev:
        expected = _expected_dev(cfg) or 'auto'
        print(f'openvpn: device is not ready yet, expected {expected}')
        print('openvpn: check logread -e openvpn')
        return

    _run(['uci', '-q', 'delete', f'network.{iface}'])
    _run(['uci', 'set', f'network.{iface}=interface'])
    _run(['uci', 'set', f'network.{iface}.proto=none'])
    _run(['uci', 'set', f'network.{iface}.device={dev}'])
    _run(['uci', 'commit', 'network'])

    rules = _out(['ip', 'rule', 'show'])
    needle = f'fwmark {mark}/{mask} lookup {table_name}'
    if needle not in rules:
        _run(['ip', 'rule', 'add', 'fwmark', f'{mark}/{mask}', 'table', table_name, 'priority', prio])
    _run(['ip', 'route', 'replace', 'default', 'dev', dev, 'table', table_name])


def status(core, cfg):
    return {
        'interface': cfg.get('interface'),
        'device': _ready_dev(cfg) or 'not-ready',
        'expected_device': _expected_dev(cfg) or '-',
        'config': cfg.get('config_path'),
        'table': cfg.get('table_name'),
    }
