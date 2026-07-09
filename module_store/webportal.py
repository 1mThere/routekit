import re
import shutil
from pathlib import Path
from subprocess import PIPE, run

PRIORITY = 1000
DEFAULTS = {
    'domain': 'v.be',
    'ip': 'auto',
    'port': 80,
    'home': '/www',
    'lan_device': 'br-lan',
    'lan_ip': 'auto',
    'users_dir': '/etc/routekit/users',
    'uhttpd_backup': '/etc/routekit/backups/uhttpd.before-webportal',
    'index_backup': '/etc/routekit/backups/www-index.before-webportal',
}


def _run(cmd, capture=False):
    if capture:
        return run(cmd, text=True, stdout=PIPE, stderr=PIPE)
    return run(cmd)


def _out(cmd):
    p = _run(cmd, True)
    return p.stdout.strip() if p.returncode == 0 else ''


def _get(cfg, key):
    return cfg.get(key) or DEFAULTS[key]


def _ipv4(value, fallback=''):
    m = re.search(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)', str(value or ''))
    return m.group(0) if m else fallback


def _lan_ip(cfg):
    ip = _ipv4(cfg.get('lan_ip')) if cfg.get('lan_ip') != 'auto' else ''
    ip = ip or _ipv4(_out(['uci', '-q', 'get', 'network.lan.ipaddr']))
    ip = ip or _ipv4(_out(['ip', '-4', 'addr', 'show', 'dev', _get(cfg, 'lan_device')]))
    return ip or DEFAULTS.get('fallback_lan_ip', '192.168.1.1')


def _write(path, data, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding='utf-8') if path.exists() else None
    changed = old != data
    if changed:
        path.write_text(data, encoding='utf-8')
    if mode is not None and (path.stat().st_mode & 0o777) != mode:
        path.chmod(mode)
        changed = True
    return changed


def _remove(path):
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _backup(src, dst):
    src = Path(src)
    dst = Path(dst)
    if src.exists() and not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _restore(src, dst):
    src = Path(src)
    if src.exists():
        shutil.copy2(src, dst)
        return True
    return False


def enable(core, cfg):
    domain = input(f'portal domain [{cfg.get("domain", DEFAULTS["domain"])}]: ').strip()
    cfg['domain'] = domain or cfg.get('domain', DEFAULTS['domain'])
    cfg['ip'] = 'auto'
    cfg['port'] = DEFAULTS['port']
    cfg['home'] = DEFAULTS['home']
    cfg['users_dir'] = cfg.get('users_dir', DEFAULTS['users_dir'])


def render(core, cfg):
    cfg['ip'] = 'auto'
    cfg['port'] = DEFAULTS['port']
    cfg['home'] = DEFAULTS['home']

    users_dir = Path(_get(cfg, 'users_dir'))
    users_dir.mkdir(parents=True, exist_ok=True)

    dns_dir = Path(core.config['dnsmasq_confdir'])
    dns_dir.mkdir(parents=True, exist_ok=True)
    _ensure_dnsmasq_confdir(dns_dir)
    dns_changed = _write(dns_dir / 'routekit-webportal.conf', f'address=/{_get(cfg, "domain")}/{_lan_ip(cfg)}\n')

    _backup('/www/index.html', _get(cfg, 'index_backup'))
    _write('/www/index.html', _index_html(list(getattr(core, 'portal_tiles', []))))
    _write('/www/cgi-bin/routekit-user', _user_api(str(users_dir)), 0o755)

    return ['dnsmasq', 'uhttpd'] if dns_changed else ['uhttpd']


def apply(core, cfg):
    cfg['ip'] = 'auto'
    cfg['port'] = DEFAULTS['port']
    cfg['home'] = DEFAULTS['home']
    _remove_legacy_ip(cfg)
    _remove('/etc/hotplug.d/iface/90-routekit-webportal-ip')
    _configure_uhttpd(cfg)
    _run(['/etc/init.d/uhttpd', 'enable'])
    _run(['/etc/init.d/uhttpd', 'restart'])


def cleanup(core, cfg):
    _remove_legacy_ip(cfg)
    _remove('/www/cgi-bin/routekit-user')
    _remove(Path(core.config['dnsmasq_confdir']) / 'routekit-webportal.conf')
    _restore(_get(cfg, 'index_backup'), '/www/index.html')
    if not _restore(_get(cfg, 'uhttpd_backup'), '/etc/config/uhttpd'):
        _run(['uci', '-q', 'delete', 'uhttpd.routekit'])
        _run(['uci', 'commit', 'uhttpd'])
    _run(['/etc/init.d/uhttpd', 'enable'])
    return ['dnsmasq', 'uhttpd']


def status(core, cfg):
    users_dir = Path(_get(cfg, 'users_dir'))
    users = len(list(users_dir.glob('*.json'))) if users_dir.exists() else 0
    lan_ip = _lan_ip(cfg)
    return {
        'domain': _get(cfg, 'domain'),
        'ip': lan_ip,
        'port': DEFAULTS['port'],
        'home': DEFAULTS['home'],
        'users': users,
        'url': f'http://{_get(cfg, "domain")}',
        'luci': f'http://{lan_ip}/cgi-bin/luci',
    }


def _ensure_dnsmasq_confdir(path):
    path = str(path)
    if path not in _out(['uci', '-q', 'get', 'dhcp.@dnsmasq[0].confdir']).splitlines():
        _run(['uci', 'add_list', f'dhcp.@dnsmasq[0].confdir={path}'])
        _run(['uci', 'commit', 'dhcp'])


def _configure_uhttpd(cfg):
    _backup('/etc/config/uhttpd', _get(cfg, 'uhttpd_backup'))
    lan_ip = _lan_ip(cfg)
    for cmd in (
        ['uci', '-q', 'delete', 'uhttpd.routekit'],
        ['uci', '-q', 'set', 'uhttpd.main=uhttpd'],
        ['uci', '-q', 'delete', 'uhttpd.main.listen_http'],
        ['uci', '-q', 'delete', 'uhttpd.main.listen_https'],
        ['uci', 'add_list', f'uhttpd.main.listen_http={lan_ip}:80'],
        ['uci', 'set', 'uhttpd.main.home=/www'],
        ['uci', 'set', 'uhttpd.main.cgi_prefix=/cgi-bin'],
        ['uci', 'set', 'uhttpd.main.redirect_https=0'],
        ['uci', 'set', 'uhttpd.main.rfc1918_filter=0'],
        ['uci', 'commit', 'uhttpd'],
    ):
        _run(cmd)


def _remove_legacy_ip(cfg):
    ip = _ipv4(cfg.get('ip'))
    dev = _get(cfg, 'lan_device')
    if not ip or ip == _lan_ip(cfg):
        return
    for line in _out(['ip', '-o', '-4', 'addr', 'show', 'dev', dev]).splitlines():
        addr = line.split()[3]
        if addr.split('/', 1)[0] == ip:
            _run(['ip', 'addr', 'del', addr, 'dev', dev])


def _index_html(tiles):
    body = '\n'.join(tiles) or '<section><h2>Модули не подключены</h2></section>'
    return f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RouteKit</title>
<style>body{{max-width:960px;margin:38px auto;padding:0 18px;background:#0b0d10;color:#e7eaf0;font-family:Arial,sans-serif}}section{{background:#11151b;border:1px solid #2a303a;border-radius:12px;padding:18px 20px;margin:14px 0}}select,button{{padding:10px}}</style>
</head>
<body>
<h1>RouteKit</h1>
{body}
<script>fetch('/cgi-bin/routekit-user',{{cache:'no-store'}}).catch(()=>{{}});</script>
</body>
</html>
'''


def _user_api(users_dir):
    return f'''#!/usr/bin/python3
import json
from pathlib import Path
users_dir = Path({users_dir!r})
users_dir.mkdir(parents=True, exist_ok=True)
print('Content-Type: application/json; charset=utf-8')
print('Cache-Control: no-store')
print()
print(json.dumps({{'ok': True}}, ensure_ascii=False))
'''
