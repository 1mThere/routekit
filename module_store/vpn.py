import json
from pathlib import Path

PRIORITY = 20
DEFAULTS = {
    'provider': 'openvpn',
    'list_path': '/etc/routekit/lists/standard.txt',
    'users_dir': '/etc/routekit/users',
    'dst_set': 'rk_vpn_dst4',
    'standard_src_set': 'rk_vpn_standard_src4',
    'all_src_set': 'rk_vpn_all_src4',
    'chain_name': 'rk_vpn_prerouting',
    'mark': '0x00520000',
    'mark_mask': '0x00ff0000',
}


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding='utf-8')


def _domains(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
        d = line.strip().lower()
        if d and not d.startswith('#'):
            out.append(d)
    return sorted(set(out))


def _users(path):
    root = Path(path)
    if not root.exists():
        return []
    out = []
    for p in root.glob('*.json'):
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        ip = str(data.get('ip') or '').strip()
        mode = str(data.get('mode') or 'direct').strip()
        if ip and mode in ('direct', 'standard', 'vpn_all'):
            out.append(data)
    return out


def _set_block(name, ips=None):
    ips = sorted(set(ips or []))
    elements = ''
    if ips:
        elements = '\n                elements = { ' + ', '.join(ips) + ' }'
    return f'''        set {name} {{
                type ipv4_addr
                flags interval
                auto-merge{elements}
        }}'''


def enable(core, cfg):
    print('vpn module uses per-user configs created by webportal.')
    print('default mode is direct; users choose direct, standard, or vpn_all in the portal.')
    cfg['provider'] = input(f'provider [{cfg.get("provider", "openvpn")}]: ').strip() or cfg.get('provider', 'openvpn')


def render(core, cfg):
    domains = _domains(cfg['list_path'])
    users = _users(cfg['users_dir'])
    dnsmasq_dir = Path(core.config['dnsmasq_confdir'])
    fw4_dir = Path(core.config['fw4_post_dir'])

    dns_lines = [f'nftset=/{d}/4#inet#fw4#{cfg["dst_set"]}' for d in domains]
    _write(dnsmasq_dir / 'routekit-vpn.conf', '\n'.join(dns_lines) + ('\n' if dns_lines else ''))

    standard_ips = [u['ip'] for u in users if u.get('mode') == 'standard']
    all_ips = [u['ip'] for u in users if u.get('mode') == 'vpn_all']

    lan = core.config.get('lan_iface', 'br-lan')
    nft = f'''table inet fw4 {{
{_set_block(cfg['dst_set'])}

{_set_block(cfg['standard_src_set'], standard_ips)}

{_set_block(cfg['all_src_set'], all_ips)}

        chain {cfg['chain_name']} {{
                type filter hook prerouting priority -155; policy accept;
                meta mark & {cfg['mark_mask']} != 0 return
                iifname "{lan}" ip saddr @{cfg['all_src_set']} meta mark set meta mark & 0xff00ffff | {cfg['mark']} comment "routekit user vpn_all"
                iifname "{lan}" ip saddr @{cfg['standard_src_set']} ip daddr @{cfg['dst_set']} meta mark set meta mark & 0xff00ffff | {cfg['mark']} comment "routekit user standard"
        }}
}}
'''
    _write(fw4_dir / '40-routekit-vpn.nft', nft)
    return ['firewall', 'dnsmasq']


def status(core, cfg):
    users = _users(cfg['users_dir'])
    return {
        'provider': cfg.get('provider'),
        'domains': len(_domains(cfg['list_path'])),
        'users': len(users),
        'direct': sum(1 for u in users if u.get('mode') == 'direct'),
        'standard': sum(1 for u in users if u.get('mode') == 'standard'),
        'vpn_all': sum(1 for u in users if u.get('mode') == 'vpn_all'),
    }
