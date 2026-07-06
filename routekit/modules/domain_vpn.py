from pathlib import Path

from .base import Module
from ..domains import read_list
from ..system import atomic_write


class DomainVpnModule(Module):
    name = 'domain_vpn'
    priority = 40
    defaults = {
        'enabled': False,
        'provider': 'provider_openwrt_iface',
        'list_path': '/etc/routekit/lists/standard.txt',
        'set_name': 'rk_domain_vpn_dst4',
        'chain_name': 'rk_domain_vpn_prerouting',
        'mark': '0x00520000',
        'mark_mask': '0x00ff0000',
    }

    def render(self):
        cfg = self.cfg()
        domains = read_list(cfg['list_path'])
        dnsmasq_dir = Path(self.core.config['dnsmasq_confdir'])
        fw4_dir = Path(self.core.config['fw4_post_dir'])
        dnsmasq_file = dnsmasq_dir / 'routekit-domain-vpn.conf'
        nft_file = fw4_dir / '40-routekit-domain-vpn.nft'

        dns_lines = [f'nftset=/{d}/4#inet#fw4#{cfg["set_name"]}' for d in domains]
        atomic_write(dnsmasq_file, '\n'.join(dns_lines) + ('\n' if dns_lines else ''))

        lan = self.core.config.get('lan_iface', 'br-lan')
        set_name = cfg['set_name']
        chain_name = cfg['chain_name']
        mark = cfg['mark']
        mask = cfg['mark_mask']
        nft = f'''table inet fw4 {{
        set {set_name} {{
                type ipv4_addr
                flags interval
                auto-merge
        }}

        chain {chain_name} {{
                type filter hook prerouting priority -155; policy accept;
                meta mark & {mask} != 0 return
                iifname "{lan}" ip daddr @{set_name} meta mark set meta mark & 0xff00ffff | {mark} comment "routekit domain_vpn"
        }}
}}
'''
        atomic_write(nft_file, nft)
        return ['firewall', 'dnsmasq']

    def status(self):
        cfg = self.cfg()
        return {
            'list_path': cfg['list_path'],
            'domains': len(read_list(cfg['list_path'])),
            'set': cfg['set_name'],
        }
