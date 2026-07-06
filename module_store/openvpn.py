import ipaddress
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
    'runtime_config_path': '/etc/openvpn/routekit_openvpn.runtime.ovpn',
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


def _is_tunnel(dev):
    return dev.startswith('tun') or dev.startswith('tap') or dev.startswith('ovpn') or dev.startswith('wg')


def _dev_exists(dev):
    if not dev:
        return False
    return run(['ip', 'link', 'show', 'dev', dev], text=True, stdout=PIPE, stderr=PIPE).returncode == 0


def _first_tunnel_dev():
    links = _out(['ip', '-o', 'link', 'show']).splitlines()
    for line in links:
        name = line.split(':', 2)[1].strip().split('@', 1)[0]
        if _is_tunnel(name):
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


def _clean_config(src, dst):
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    skip = {'redirect-gateway', 'route', 'route-ipv6', 'route-nopull'}
    lines = []
    for raw in src.read_text(encoding='utf-8', errors='ignore').splitlines():
        stripped = raw.strip()
        token = stripped.split(None, 1)[0] if stripped else ''
        if token in skip:
            continue
        lines.append(raw)
    lines.append('route-nopull')
    data = '\n'.join(lines).rstrip() + '\n'
    old = dst.read_text(encoding='utf-8', errors='ignore') if dst.exists() else None
    if old != data:
        dst.write_text(data, encoding='utf-8')
    return str(dst)


def _route_dev(line):
    parts = line.split()
    if 'dev' not in parts:
        return ''
    i = parts.index('dev')
    if i + 1 >= len(parts):
        return ''
    return parts[i + 1]


def _cleanup_main_tunnel_routes():
    for line in _out(['ip', 'route', 'show']).splitlines():
        target = line.split(None, 1)[0] if line else ''
        if target not in ('default', '0.0.0.0/1', '128.0.0.0/1'):
            continue
        dev = _route_dev(line)
        if not _is_tunnel(dev):
            continue
        _run(['ip', 'route', 'del'] + line.split())


def _ensure_rt_table(table_id, table_name):
    rt = Path('/etc/iproute2/rt_tables')
    current = rt.read_text(encoding='utf-8', errors='ignore') if rt.exists() else ''
    if f'{table_id} {table_name}' not in current:
        with rt.open('a', encoding='utf-8') as f:
            f.write(f'{table_id} {table_name}\n')


def _ensure_wan_network(iface):
    lines = _out(['uci', '-q', 'show', 'firewall']).splitlines()
    zones = []
    for line in lines:
        left, _, right = line.partition('=')
        if right == 'zone' and left.startswith('firewall.@'):
            zones.append(left[len('firewall.'):])
    for zone in zones:
        if _out(['uci', '-q', 'get', f'firewall.{zone}.name']) != 'wan':
            continue
        networks = _out(['uci', '-q', 'get', f'firewall.{zone}.network']).split()
        if iface not in networks:
            _run(['uci', 'add_list', f'firewall.{zone}.network={iface}'])
            _run(['uci', 'commit', 'firewall'])
        return


def _sync_network_iface(iface, dev):
    old = _out(['uci', '-q', 'get', f'network.{iface}.device'])
    changed = old != dev or _out(['uci', '-q', 'get', f'network.{iface}.proto']) != 'none'
    _run(['uci', '-q', 'delete', f'network.{iface}'])
    _run(['uci', 'set', f'network.{iface}=interface'])
    _run(['uci', 'set', f'network.{iface}.proto=none'])
    _run(['uci', 'set', f'network.{iface}.device={dev}'])
    _run(['uci', 'commit', 'network'])
    _run(['ifdown', iface])
    _run(['ifup', iface])
    return changed


def _peer_gateway(dev):
    for line in _out(['ip', '-4', 'addr', 'show', 'dev', dev]).splitlines():
        parts = line.split()
        if 'inet' not in parts:
            continue
        if 'peer' in parts:
            peer = parts[parts.index('peer') + 1].split('/', 1)[0]
            return peer
        cidr = parts[parts.index('inet') + 1]
        try:
            iface = ipaddress.ip_interface(cidr)
        except Exception:
            continue
        net = iface.network
        if net.num_addresses <= 2:
            continue
        gw = net.network_address + 1
        if gw == iface.ip and net.num_addresses > 3:
            gw = net.network_address + 2
        return str(gw)
    return ''


def _replace_vpn_default_route(table_name, dev):
    _run(['ip', 'route', 'flush', 'table', table_name])
    gw = _peer_gateway(dev)
    if gw:
        p = _run(['ip', 'route', 'replace', 'default', 'via', gw, 'dev', dev, 'table', table_name])
        if p.returncode == 0:
            return gw
    _run(['ip', 'route', 'replace', 'default', 'dev', dev, 'table', table_name])
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
    runtime_config_path = cfg.get('runtime_config_path') or '/etc/openvpn/routekit_openvpn.runtime.ovpn'
    iface = cfg.get('interface', 'vpnclient')

    _cleanup_main_tunnel_routes()

    if config_path and Path(config_path).exists():
        active_config = _clean_config(config_path, runtime_config_path)
        _run(['uci', '-q', 'delete', 'openvpn.routekit_openvpn'])
        _run(['uci', 'set', 'openvpn.routekit_openvpn=openvpn'])
        _run(['uci', 'set', 'openvpn.routekit_openvpn.enabled=1'])
        _run(['uci', 'set', f'openvpn.routekit_openvpn.config={active_config}'])
        _run(['uci', 'commit', 'openvpn'])
        _run(['/etc/init.d/openvpn', 'enable'])
        _run(['/etc/init.d/openvpn', 'restart'])

    table_id = str(cfg['table_id'])
    table_name = str(cfg['table_name'])
    mark = str(cfg['mark'])
    mask = str(cfg['mark_mask'])
    prio = str(cfg['priority'])

    _ensure_rt_table(table_id, table_name)

    dev = _wait_ready_dev(cfg)
    if not dev:
        expected = _expected_dev(cfg) or 'auto'
        print(f'openvpn: device is not ready yet, expected {expected}')
        print('openvpn: check logread -e openvpn')
        return

    _sync_network_iface(iface, dev)
    _ensure_wan_network(iface)
    _run(['/etc/init.d/firewall', 'restart'])

    rules = _out(['ip', 'rule', 'show'])
    needle = f'fwmark {mark}/{mask} lookup {table_name}'
    if needle not in rules:
        _run(['ip', 'rule', 'add', 'fwmark', f'{mark}/{mask}', 'table', table_name, 'priority', prio])
    gateway = _replace_vpn_default_route(table_name, dev)
    _cleanup_main_tunnel_routes()
    if gateway:
        print(f'openvpn: gateway {gateway}')


def is_ready(core, cfg):
    return bool(_ready_dev(cfg))


def status(core, cfg):
    return {
        'interface': cfg.get('interface'),
        'device': _ready_dev(cfg) or 'not-ready',
        'gateway': _peer_gateway(_ready_dev(cfg)) if _ready_dev(cfg) else '-',
        'expected_device': _expected_dev(cfg) or '-',
        'config': cfg.get('config_path'),
        'table': cfg.get('table_name'),
    }
