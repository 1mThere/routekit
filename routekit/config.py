import json
from pathlib import Path

ETC = Path('/etc/routekit')
CONFIG_PATH = ETC / 'config.json'

DEFAULT_CONFIG = {
    'lan_iface': 'br-lan',
    'dnsmasq_confdir': '/etc/dnsmasq.d',
    'fw4_post_dir': '/usr/share/nftables.d/ruleset-post',
    'modules': {},
}


def load_config():
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG.copy())
    with CONFIG_PATH.open('r', encoding='utf-8') as f:
        cfg = json.load(f)
    merged = DEFAULT_CONFIG.copy()
    merged.update(cfg)
    merged.setdefault('modules', {})
    return merged


def save_config(cfg):
    ETC.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open('w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')


def module_cfg(cfg, name):
    return cfg.setdefault('modules', {}).setdefault(name, {})
