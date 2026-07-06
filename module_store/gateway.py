from subprocess import run, PIPE

PRIORITY = 5
DEFAULTS = {
    'lan_zone': 'lan',
    'wan_zone': 'wan',
    'lan_network': 'lan',
    'wan_networks': ['wan', 'wan6'],
    'lan_input': 'ACCEPT',
    'lan_output': 'ACCEPT',
    'lan_forward': 'ACCEPT',
    'wan_input': 'REJECT',
    'wan_output': 'ACCEPT',
    'wan_forward': 'REJECT',
    'wan_masq': '1',
    'wan_mtu_fix': '1',
    'enable_ipv4_forward': True,
}


def _run(argv):
    return run(argv, text=True, stdout=PIPE, stderr=PIPE)


def _out(argv):
    p = _run(argv)
    if p.returncode != 0:
        return ''
    return p.stdout.strip()


def _uci_get(key):
    return _out(['uci', '-q', 'get', key])


def _uci_set(key, value):
    cur = _uci_get(key)
    if cur == str(value):
        return False
    _run(['uci', 'set', f'{key}={value}'])
    return True


def _sections(kind):
    out = []
    marker = '=' + kind
    for line in _out(['uci', '-q', 'show', 'firewall']).splitlines():
        if marker not in line:
            continue
        left, _, right = line.partition('=')
        if right == kind and left.startswith('firewall.@'):
            out.append(left[len('firewall.'):])
    return out


def _zone(name):
    for section in _sections('zone'):
        if _uci_get(f'firewall.{section}.name') == name:
            return section
    return ''


def _new(kind):
    p = _run(['uci', 'add', 'firewall', kind])
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or f'cannot add firewall {kind}')
    return '@' + kind + '[-1]'


def _list_values(key):
    return _uci_get(key).split()


def _ensure_list(key, value):
    if value in _list_values(key):
        return False
    _run(['uci', 'add_list', f'{key}={value}'])
    return True


def _ensure_zone(name, networks, values):
    changed = False
    section = _zone(name)
    if not section:
        section = _new('zone')
        changed |= _uci_set(f'firewall.{section}.name', name)
    for k, v in values.items():
        changed |= _uci_set(f'firewall.{section}.{k}', v)
    for net in networks:
        changed |= _ensure_list(f'firewall.{section}.network', net)
    return changed


def _forwarding(src, dest):
    for section in _sections('forwarding'):
        if _uci_get(f'firewall.{section}.src') == src and _uci_get(f'firewall.{section}.dest') == dest:
            return section
    return ''


def _ensure_forwarding(src, dest):
    if _forwarding(src, dest):
        return False
    section = _new('forwarding')
    changed = False
    changed |= _uci_set(f'firewall.{section}.src', src)
    changed |= _uci_set(f'firewall.{section}.dest', dest)
    return changed


def _commit(changed):
    if changed:
        _run(['uci', 'commit', 'firewall'])
    return changed


def _enable_ipv4_forward():
    try:
        p = _run(['sysctl', '-w', 'net.ipv4.ip_forward=1'])
        return p.returncode == 0
    except Exception:
        return False


def render(core, cfg):
    lan_zone = cfg.get('lan_zone', 'lan')
    wan_zone = cfg.get('wan_zone', 'wan')
    lan_network = cfg.get('lan_network', 'lan')
    wan_networks = cfg.get('wan_networks') or ['wan', 'wan6']
    if isinstance(wan_networks, str):
        wan_networks = [x for x in wan_networks.replace(',', ' ').split() if x]

    changed = False
    changed |= _ensure_zone(lan_zone, [lan_network], {
        'input': cfg.get('lan_input', 'ACCEPT'),
        'output': cfg.get('lan_output', 'ACCEPT'),
        'forward': cfg.get('lan_forward', 'ACCEPT'),
    })
    changed |= _ensure_zone(wan_zone, wan_networks, {
        'input': cfg.get('wan_input', 'REJECT'),
        'output': cfg.get('wan_output', 'ACCEPT'),
        'forward': cfg.get('wan_forward', 'REJECT'),
        'masq': str(cfg.get('wan_masq', '1')),
        'mtu_fix': str(cfg.get('wan_mtu_fix', '1')),
    })
    changed |= _ensure_forwarding(lan_zone, wan_zone)
    _commit(changed)
    return ['firewall'] if changed else []


def apply(core, cfg):
    if cfg.get('enable_ipv4_forward', True):
        _enable_ipv4_forward()


def status(core, cfg):
    lan_zone = cfg.get('lan_zone', 'lan')
    wan_zone = cfg.get('wan_zone', 'wan')
    fwd = bool(_forwarding(lan_zone, wan_zone))
    return {
        'lan_zone': lan_zone,
        'wan_zone': wan_zone,
        'lan_to_wan': 'yes' if fwd else 'no',
        'wan_masq': _uci_get(f'firewall.{_zone(wan_zone)}.masq') if _zone(wan_zone) else 'missing',
    }
