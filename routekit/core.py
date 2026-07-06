import importlib.util
import subprocess
import time
import urllib.request
from pathlib import Path

from .config import MODULE_DIR, load_config, module_cfg, save_config
from .system import service_restart


STAGES = ('preflight', 'render', 'apply')


class LoadedModule:
    def __init__(self, name, py_module, core):
        self.name = name
        self.py = py_module
        self.core = core
        self.priority = int(getattr(py_module, 'PRIORITY', 100))
        self.defaults = getattr(py_module, 'DEFAULTS', {})

    def cfg(self):
        cfg = module_cfg(self.core.config, self.name)
        for k, v in self.defaults.items():
            cfg.setdefault(k, v)
        return cfg

    def call(self, stage):
        fn = getattr(self.py, stage, None)
        if not fn:
            return []
        result = fn(self.core, self.cfg())
        return result or []

    def status(self):
        fn = getattr(self.py, 'status', None)
        if not fn:
            return {}
        return fn(self.core, self.cfg()) or {}


class Core:
    def __init__(self):
        self.config = load_config()

    def save(self):
        save_config(self.config)

    def init(self):
        Path('/etc/routekit/lists').mkdir(parents=True, exist_ok=True)
        MODULE_DIR.mkdir(parents=True, exist_ok=True)
        std = Path('/etc/routekit/lists/standard.txt')
        if not std.exists():
            std.write_text('', encoding='utf-8')
        self.save()

    def registry(self):
        return self.config.setdefault('registry', {})

    def enabled_names(self):
        return list(self.config.setdefault('enabled_modules', []))

    def module_config(self, name, defaults=None):
        cfg = module_cfg(self.config, name)
        if defaults:
            for k, v in defaults.items():
                cfg.setdefault(k, v)
        return cfg

    def module_path(self, name):
        return MODULE_DIR / f'{name}.py'

    def _download_with_curl(self, url, tmp):
        return subprocess.run([
            'curl', '-fsSL', '--retry', '3', '--retry-delay', '1', '--retry-all-errors',
            '--connect-timeout', '8', '--max-time', '45', '--speed-time', '10', '--speed-limit', '512',
            url, '-o', str(tmp),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _download_with_urllib(self, url):
        req = urllib.request.Request(url, headers={'User-Agent': 'routekit'})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode('utf-8')

    def download_module(self, name, url, path):
        tmp = path.with_suffix('.tmp')
        errors = []
        if tmp.exists():
            tmp.unlink()

        for attempt in range(1, 4):
            curl = self._download_with_curl(url, tmp)
            if curl.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(path)
                return
            errors.append(f'curl attempt {attempt}: {curl.stderr.strip() or curl.returncode}')
            if tmp.exists():
                tmp.unlink()
            time.sleep(1)

        try:
            data = self._download_with_urllib(url)
            if not data.strip():
                raise RuntimeError('empty response')
            tmp.write_text(data, encoding='utf-8')
            tmp.replace(path)
            return
        except Exception as e:
            errors.append(f'python urllib: {e}')

        if tmp.exists():
            tmp.unlink()
        raise SystemExit('cannot download module ' + name + '\n' + '\n'.join(errors))

    def ensure_module_downloaded(self, name, force=False):
        reg = self.registry().get(name)
        if not reg:
            raise SystemExit(f'unknown module: {name}')
        if not reg.get('implemented', True):
            raise SystemExit(f'module {name} is not implemented yet')

        path = self.module_path(name)
        if path.exists() and not force:
            return path

        url = reg.get('url')
        if not url:
            raise SystemExit(f'module {name} has no download url')

        MODULE_DIR.mkdir(parents=True, exist_ok=True)
        action = 'refreshing' if path.exists() else 'downloading'
        print(f'{action} module {name}: {url}')
        self.download_module(name, url, path)
        return path

    def refresh_module(self, name):
        return self.ensure_module_downloaded(name, force=True)

    def refresh_modules(self, enabled_only=True):
        if enabled_only:
            names = self.enabled_names()
        else:
            names = sorted(self.registry())
        for name in names:
            reg = self.registry().get(name, {})
            if reg.get('implemented', True):
                self.refresh_module(name)

    def _load_module_file(self, name, path):
        spec = importlib.util.spec_from_file_location(f'routekit_runtime_{name}', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return LoadedModule(name, mod, self)

    def load_module(self, name):
        return self._load_module_file(name, self.ensure_module_downloaded(name))

    def load_local_module(self, name):
        path = self.module_path(name)
        if not path.exists():
            raise SystemExit(f'module is not downloaded: {name}')
        return self._load_module_file(name, path)

    def local_modules(self):
        loaded = []
        if not MODULE_DIR.exists():
            return []
        for path in sorted(MODULE_DIR.glob('*.py')):
            try:
                loaded.append(self._load_module_file(path.stem, path))
            except Exception as e:
                print(f'skip module {path.stem}: {e}')
        return sorted(loaded, key=lambda m: m.priority)

    def modules(self, only_enabled=False):
        if only_enabled:
            names = self.enabled_names()
        else:
            names = sorted(self.registry())
        loaded = []
        for name in names:
            if only_enabled or self.module_path(name).exists():
                try:
                    loaded.append(self.load_module(name))
                except SystemExit:
                    if only_enabled:
                        raise
        return sorted(loaded, key=lambda m: m.priority)

    def enable_module(self, name):
        reg = self.registry().get(name)
        if not reg:
            raise SystemExit(f'unknown module: {name}')
        if not reg.get('implemented', True):
            raise SystemExit(f'module {name} is not implemented yet')

        missing = [d for d in reg.get('deps', []) if d not in self.enabled_names()]
        if missing:
            raise SystemExit(f'module {name} requires: {", ".join(missing)}')

        mod = self.load_module(name)
        cfg = mod.cfg()
        fn = getattr(mod.py, 'enable', None)
        if fn:
            fn(self, cfg)
        if name not in self.enabled_names():
            self.config['enabled_modules'].append(name)
        self.save()
        self.apply()

    def _cleanup_loaded(self, mods):
        services = set()
        for mod in sorted(mods, key=lambda m: m.priority, reverse=True):
            fn = getattr(mod.py, 'cleanup', None)
            if not fn:
                continue
            try:
                result = fn(self, mod.cfg()) or []
                services.update(result)
                print(f'cleaned: {mod.name}')
            except Exception as e:
                print(f'cleanup failed: {mod.name}: {e}')
        for svc in sorted(services):
            service_restart(svc)

    def cleanup_module(self, name):
        self._cleanup_loaded([self.load_local_module(name)])

    def rescue(self):
        self._cleanup_loaded(self.local_modules())
        self.config['enabled_modules'] = []
        self.save()

    def disable_module(self, name):
        if self.module_path(name).exists():
            self.cleanup_module(name)
        enabled = self.enabled_names()
        if name in enabled:
            enabled.remove(name)
        self.save()
        self.apply()

    def set_module_value(self, name, key, value):
        if name not in self.enabled_names():
            raise SystemExit(f'module is not enabled: {name}')
        mod = self.load_module(name)
        cfg = mod.cfg()
        if isinstance(value, str) and value.lower() in ('true', 'yes', 'on'):
            value = True
        elif isinstance(value, str) and value.lower() in ('false', 'no', 'off'):
            value = False
        else:
            try:
                value = int(value, 0)
            except Exception:
                pass
        cfg[key] = value
        self.save()

    def apply(self):
        mods = self.modules(only_enabled=True)

        errors = []
        for mod in mods:
            errors.extend(mod.call('preflight'))
        if errors:
            for e in errors:
                print(f'error: {e}')
            raise SystemExit(1)

        services = set()
        for mod in mods:
            services.update(mod.call('render'))
        for svc in sorted(services):
            service_restart(svc)
        for mod in mods:
            mod.call('apply')

    def doctor(self):
        print('routekit doctor')
        print(f'enabled: {", ".join(self.enabled_names()) or "none"}')
        print()
        for name, reg in sorted(self.registry().items()):
            enabled = name in self.enabled_names()
            installed = self.module_path(name).exists()
            print(f'[{name}] enabled={enabled} downloaded={installed}')
            if enabled:
                mod = self.load_module(name)
                for k, v in mod.status().items():
                    print(f'  {k}: {v}')
            print()
