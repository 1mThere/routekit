from pathlib import Path

from .config import load_config, save_config, module_cfg
from .system import service_restart
from .modules.domain_vpn import DomainVpnModule
from .modules.provider_openwrt_iface import ProviderOpenwrtIfaceModule
from .modules.portal_static import PortalStaticModule
from .modules.zapret_stub import ZapretStubModule

MODULES = {
    'provider_openwrt_iface': ProviderOpenwrtIfaceModule,
    'domain_vpn': DomainVpnModule,
    'portal_static': PortalStaticModule,
    'zapret_stub': ZapretStubModule,
}


class Core:
    def __init__(self):
        self.config = load_config()

    def save(self):
        save_config(self.config)

    def module_config(self, name, defaults=None):
        cfg = module_cfg(self.config, name)
        if defaults:
            for k, v in defaults.items():
                cfg.setdefault(k, v)
        return cfg

    def modules(self, only_enabled=False):
        items = []
        for name, cls in MODULES.items():
            mod = cls(self)
            if only_enabled and not mod.enabled():
                continue
            items.append(mod)
        return sorted(items, key=lambda m: m.priority)

    def init(self):
        Path('/etc/routekit/lists').mkdir(parents=True, exist_ok=True)
        Path('/var/lib/routekit').mkdir(parents=True, exist_ok=True)
        std = Path('/etc/routekit/lists/standard.txt')
        if not std.exists():
            std.write_text('', encoding='utf-8')
        self.save()

    def enable_module(self, name):
        if name not in MODULES:
            raise SystemExit(f'unknown module: {name}')
        cfg = self.module_config(name, MODULES[name].defaults)
        cfg['enabled'] = True
        self.save()

    def disable_module(self, name):
        if name not in MODULES:
            raise SystemExit(f'unknown module: {name}')
        cfg = self.module_config(name, MODULES[name].defaults)
        cfg['enabled'] = False
        self.save()

    def set_module_value(self, name, key, value):
        if name not in MODULES:
            raise SystemExit(f'unknown module: {name}')
        cfg = self.module_config(name, MODULES[name].defaults)
        if value.lower() in ('true', 'yes', 'on'):
            v = True
        elif value.lower() in ('false', 'no', 'off'):
            v = False
        else:
            try:
                v = int(value, 0)
            except ValueError:
                v = value
        cfg[key] = v
        self.save()

    def apply(self):
        errors = []
        for mod in self.modules(only_enabled=True):
            errors.extend(mod.preflight())
        if errors:
            for e in errors:
                print(f'error: {e}')
            raise SystemExit(1)

        services = set()
        for mod in self.modules(only_enabled=True):
            services.update(mod.render())
        for svc in sorted(services):
            service_restart(svc)
        for mod in self.modules(only_enabled=True):
            mod.apply()

    def doctor(self):
        print('routekit doctor')
        print(f'lan_iface: {self.config.get("lan_iface")}')
        print()
        for mod in self.modules():
            cfg = mod.cfg()
            print(f'[{mod.name}] enabled={cfg.get("enabled", False)}')
            st = mod.status()
            for k, v in st.items():
                print(f'  {k}: {v}')
            print()
