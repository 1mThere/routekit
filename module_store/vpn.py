from pathlib import Path

PRIORITY = 20
DEFAULTS = {
    'provider': 'openvpn',
    'list_path': '/etc/routekit/lists/standard.txt',
    'set_name': 'rk_vpn_dst4',
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


def enable(core, cfg):
    print('vpn module is global. It does not create per-device rules.')
    print('default traffic stays direct; only listed domains are marked.')
    cfg['provider'] = input(f'provider [{cfg.get("provider", "openvpn")}]: ').strip() or cfg.get('provider', 'openvpn')


def render(core, cfg):
    domains = _domains(cfg['list_path'])
    dnsmasq_dir = Path(core.config['dnsmasq_confdir'])
    fw4_dir = Path(core.config['fw4_post_dir'])

    dns_lines = [f'nftset=/{d}/4#inet#fw4#{cfg["set_name"]}' for d in domains]
    _write(dnsmasq_dir / 'routekit-vpn.conf', '\n'.join(dns_lines) + ('\n' if dns_lines else ''))

    lan = core.config.get('lan_iface', 'br-lan')
    nft = f'''table inet fw4 {{
        set {cfg['set_name']} {{
                type ipv4_addr
                flags interval
                auto-merge
        }}

        chain {cfg['chain_name']} {{
                type filter hook prerouting priority -155; policy accept;
                meta mark & {cfg['mark_mask']} != 0 return
                iifname "{lan}" ip daddr @{cfg['set_name']} meta mark set meta mark & 0xff00ffff | {cfg['mark']} comment "routekit vpn global domain"
        }}
}}
'''
    _write(fw4_dir / '40-routekit-vpn.nft', nft)
    return ['firewall', 'dnsmasq']


def status(core, cfg):
    return {
        'provider': cfg.get('provider'),
        'domains': len(_domains(cfg['list_path'])),
        'mode': 'global domain list',
    }
