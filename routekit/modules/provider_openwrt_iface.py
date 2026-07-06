import json
from pathlib import Path

from .base import Module
from ..system import out, run, CommandError


class ProviderOpenwrtIfaceModule(Module):
    name = 'provider_openwrt_iface'
    priority = 20
    defaults = {
        'enabled': False,
        'interface': 'vpnclient',
        'table_id': 1001,
        'table_name': 'rk_vpn',
        'mark': '0x00520000',
        'mark_mask': '0x00ff0000',
        'priority': 25000,
    }

    def iface(self):
        return self.cfg()['interface']

    def get_dev(self):
        iface = self.iface()
        try:
            raw = out(['ubus', 'call', f'network.interface.{iface}', 'status'])
            data = json.loads(raw)
            dev = data.get('l3_device') or data.get('device')
            if dev:
                return dev
        except Exception:
            pass
        try:
            dev = out(['uci', '-q', 'get', f'network.{iface}.device']).strip()
            return dev or None
        except Exception:
            return None

    def preflight(self):
        errors = []
        if not self.get_dev():
            errors.append(f'provider_openwrt_iface: no device for interface {self.iface()}')
        return errors

    def apply(self):
        cfg = self.cfg()
        dev = self.get_dev()
        if not dev:
            return []

        table_id = str(cfg['table_id'])
        table_name = str(cfg['table_name'])
        mark = str(cfg['mark'])
        mask = str(cfg['mark_mask'])
        prio = str(cfg['priority'])

        rt_tables = Path('/etc/iproute2/rt_tables')
        current = rt_tables.read_text(encoding='utf-8', errors='ignore') if rt_tables.exists() else ''
        line = f'{table_id} {table_name}'
        if line not in current:
            with rt_tables.open('a', encoding='utf-8') as f:
                f.write(line + '\n')

        rules = out(['ip', 'rule', 'show'])
        needle = f'fwmark {mark}/{mask} lookup {table_name}'
        if needle not in rules:
            run(['ip', 'rule', 'add', 'fwmark', f'{mark}/{mask}', 'table', table_name, 'priority', prio], check=False)

        run(['ip', 'route', 'replace', 'default', 'dev', dev, 'table', table_name], check=False)
        return []

    def status(self):
        cfg = self.cfg()
        return {
            'interface': cfg['interface'],
            'device': self.get_dev() or '-',
            'table': cfg['table_name'],
            'mark': f"{cfg['mark']}/{cfg['mark_mask']}",
        }
