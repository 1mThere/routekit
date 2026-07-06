import json
from pathlib import Path

ETC = Path('/etc/routekit')
CONFIG_PATH = ETC / 'config.json'
MODULE_DIR = Path('/var/lib/routekit/modules')

BASE_URL = 'https://raw.githubusercontent.com/1mThere/routekit/main/module_store'

DEFAULT_CONFIG = {
    'lan_iface': 'br-lan',
    'dnsmasq_confdir': '/etc/dnsmasq.d',
    'fw4_post_dir': '/usr/share/nftables.d/ruleset-post',
    'enabled_modules': [],
    'modules': {},
    'registry': {
        'gateway': {
            'url': f'{BASE_URL}/gateway.py',
            'deps': [],
            'implemented': True,
            'auto_enable': True,
        },
        'webportal': {
            'url': f'{BASE_URL}/webportal.py',
            'deps': [],
            'implemented': True,
        },
        'vpn': {
            'url': f'{BASE_URL}/vpn.py',
            'deps': ['webportal', 'gateway'],
            'implemented': True,
        },
        'openvpn': {
            'url': f'{BASE_URL}/openvpn.py',
            'deps': ['vpn'],
            'implemented': True,
        },
        'zapret': {
            'url': f'{BASE_URL}/zapret.py',
            'deps': ['webportal'],
            'implemented': False,
        },
    },
}


def _merge_defaults(cfg):
    merged = DEFAULT_CONFIG.copy()
    merged.update(cfg)
    merged.setdefault('enabled_modules', [])
    merged.setdefault('modules', {})
    registry = DEFAULT_CONFIG['registry'].copy()
    registry.update(merged.get('registry', {}))
    for name, default in DEFAULT_CONFIG['registry'].items():
        current = registry.setdefault(name, {})
        for k, v in default.items():
            current.setdefault(k, v)
    merged['registry'] = registry
    return merged


def load_config():
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG.copy())
    with CONFIG_PATH.open('r', encoding='utf-8') as f:
        cfg = json.load(f)
    return _merge_defaults(cfg)


def save_config(cfg):
    ETC.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open('w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')


def module_cfg(cfg, name):
    return cfg.setdefault('modules', {}).setdefault(name, {})
