import json
import shutil
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
}


def _out(argv):
    p = run(argv, text=True, stdout=PIPE, stderr=PIPE)
    if p.returncode != 0:
        return ''
    return p.stdout.strip()


def _run(argv):
    return run(argv)


def _ask(prompt, default=''):
    suffix = f' [{default}]' if default else ''
    return input(f'{prompt}{suffix}: ').strip() or default


def enable(core, cfg):
    src = _ask('OpenVPN config file path or URL', '')
    if src:
        dst = Path(cfg.get('config_path') or '/etc/openvpn/routekit_openvpn.ovpn')
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.startswith('http://') or src.startswith('https://'):
            with urllib.request.urlopen(src, timeout=60) as r:
                dst.write_bytes(r.read())
        else:
            shutil.copy2(src, dst)
        cfg['config_path'] = str(dst)

    cfg['interface'] = _ask('OpenWrt network interface', cfg.get('interface', 'vpnclient'))
    cfg['device'] = _ask('VPN device, or auto', cfg.get('device', 'auto'))


def _get_dev(cfg):
    manual = cfg.get('device')
    if manual and manual != 'auto':
        return manual

    iface = cfg.get('interface', 'vpnclient')
    raw = _out(['ubus', 'call', f'network.interface.{iface}', 'status'])
    if raw:
        try:
            data = json.loads(raw)
            dev = data.get('l3_device') or data.get('device')
            if dev:
                return dev
        except Exception:
            pass

    dev = _out(['uci', '-q', 'get', f'network.{iface}.device'])
    if dev:
        return dev

    links = _out(['ip', '-o', 'link', 'show']).splitlines()
    for line in links:
        name = line.split(':', 2)[1].strip().split('@', 1)[0]
        if name.startswith('tun') or name.startswith('tap') or name.startswith('ovpn') or name.startswith('wg'):
            return name
    return ''


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

    _run(['uci', '-q', 'delete', f'network.{iface}'])
    _run(['uci', 'set', f'network.{iface}=interface'])
    _run(['uci', 'set', f'network.{iface}.proto=none'])
    dev = _get_dev(cfg)
    if dev:
        _run(['uci', 'set', f'network.{iface}.device={dev}'])
    _run(['uci', 'commit', 'network'])

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

    dev = _get_dev(cfg)
    if dev:
        rules = _out(['ip', 'rule', 'show'])
        needle = f'fwmark {mark}/{mask} lookup {table_name}'
        if needle not in rules:
            _run(['ip', 'rule', 'add', 'fwmark', f'{mark}/{mask}', 'table', table_name, 'priority', prio])
        _run(['ip', 'route', 'replace', 'default', 'dev', dev, 'table', table_name])


def status(core, cfg):
    return {
        'interface': cfg.get('interface'),
        'device': _get_dev(cfg) or '-',
        'config': cfg.get('config_path'),
        'table': cfg.get('table_name'),
    }
