import re
import shutil
from pathlib import Path
from subprocess import PIPE, run

PRIORITY = 1000
DEFAULTS = {
    'domain': 'v.be',
    'ip': '',
    'port': 80,
    'https_port': 443,
    'home': '/www-routekit',
    'lan_device': 'br-lan',
    'users_dir': '/etc/routekit/users',
    'uhttpd_backup': '/etc/routekit/backups/uhttpd.before-webportal',
    'index_backup': '/etc/routekit/backups/www-index.before-webportal',
    'cert': '/etc/uhttpd.crt',
    'key': '/etc/uhttpd.key',
}


def _run(cmd, capture=False):
    if capture:
        return run(cmd, text=True, stdout=PIPE, stderr=PIPE)
    return run(cmd)


def _out(cmd):
    p = _run(cmd, True)
    return p.stdout.strip() if p.returncode == 0 else ''


def _get(cfg, key):
    if key == 'home':
        return DEFAULTS['home']
    return cfg.get(key) or DEFAULTS[key]


def _ipv4(value):
    m = re.fullmatch(r'\s*((?:\d{1,3}\.){3}\d{1,3})(?:/\d{1,2})?\s*', str(value or ''))
    return m.group(1) if m else ''


def _portal_ip(cfg):
    ip = _ipv4(cfg.get('ip'))
    if not ip:
        raise SystemExit('webportal.ip is required')
    return ip


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
    if not src.exists():
        return False
    shutil.copy2(src, dst)
    return True


def enable(core, cfg):
    domain_default = cfg.get('domain') or DEFAULTS['domain']
    ip_default = cfg.get('ip') or ''
    domain = input(f'portal domain [{domain_default}]: ').strip()
    ip = input(f'portal ip [{ip_default}]: ').strip() or ip_default
    if not _ipv4(ip):
        raise SystemExit('webportal.ip is required')
    cfg['domain'] = domain or domain_default
    cfg['ip'] = _ipv4(ip)
    cfg['port'] = DEFAULTS['port']
    cfg['https_port'] = DEFAULTS['https_port']
    cfg['home'] = DEFAULTS['home']
    cfg['users_dir'] = cfg.get('users_dir') or DEFAULTS['users_dir']
    cfg['cert'] = cfg.get('cert') or DEFAULTS['cert']
    cfg['key'] = cfg.get('key') or DEFAULTS['key']


def render(core, cfg):
    ip = _portal_ip(cfg)
    home = Path(_get(cfg, 'home'))
    users_dir = Path(_get(cfg, 'users_dir'))
    dns_dir = Path(core.config['dnsmasq_confdir'])

    home.mkdir(parents=True, exist_ok=True)
    users_dir.mkdir(parents=True, exist_ok=True)
    dns_dir.mkdir(parents=True, exist_ok=True)

    _ensure_dnsmasq_confdir(dns_dir)
    dns_changed = _write(dns_dir / 'routekit-webportal.conf', f'address=/{_get(cfg, "domain")}/{ip}\n')
    _write(home / 'index.html', _index_html(list(getattr(core, 'portal_tiles', []))))
    _write(home / 'cgi-bin' / 'routekit-user', _user_api(str(users_dir)), 0o755)

    return ['dnsmasq', 'uhttpd'] if dns_changed else ['uhttpd']


def apply(core, cfg):
    ip = _portal_ip(cfg)
    _restore(_get(cfg, 'index_backup'), '/www/index.html')
    _run(['ip', 'addr', 'replace', f'{ip}/32', 'dev', _get(cfg, 'lan_device')])
    _configure_uhttpd(cfg)
    _run(['/etc/init.d/uhttpd', 'enable'])
    _run(['/etc/init.d/uhttpd', 'restart'])


def cleanup(core, cfg):
    _remove_ip(cfg)
    _remove(_get(cfg, 'home'))
    _remove(Path(core.config['dnsmasq_confdir']) / 'routekit-webportal.conf')
    _restore(_get(cfg, 'index_backup'), '/www/index.html')
    _run(['uci', '-q', 'delete', 'uhttpd.routekit'])
    _run(['uci', 'commit', 'uhttpd'])
    _run(['/etc/init.d/uhttpd', 'enable'])
    return ['dnsmasq', 'uhttpd']


def status(core, cfg):
    users_dir = Path(_get(cfg, 'users_dir'))
    users = len(list(users_dir.glob('*.json'))) if users_dir.exists() else 0
    return {
        'domain': _get(cfg, 'domain'),
        'ip': cfg.get('ip') or '',
        'port': DEFAULTS['port'],
        'https_port': DEFAULTS['https_port'],
        'home': _get(cfg, 'home'),
        'users': users,
        'url': f'http://{_get(cfg, "domain")}',
        'https_url': f'https://{_get(cfg, "domain")}',
    }


def _ensure_dnsmasq_confdir(path):
    path = str(path)
    if path not in _out(['uci', '-q', 'get', 'dhcp.@dnsmasq[0].confdir']).splitlines():
        _run(['uci', 'add_list', f'dhcp.@dnsmasq[0].confdir={path}'])
        _run(['uci', 'commit', 'dhcp'])


def _configure_uhttpd(cfg):
    _backup('/etc/config/uhttpd', _get(cfg, 'uhttpd_backup'))
    ip = _portal_ip(cfg)
    for cmd in (
        ['uci', '-q', 'delete', 'uhttpd.routekit'],
        ['uci', 'set', 'uhttpd.routekit=uhttpd'],
        ['uci', 'set', f'uhttpd.routekit.home={_get(cfg, "home")}'],
        ['uci', 'set', 'uhttpd.routekit.cgi_prefix=/cgi-bin'],
        ['uci', 'set', f'uhttpd.routekit.listen_http={ip}:80'],
        ['uci', 'set', f'uhttpd.routekit.listen_https={ip}:443'],
        ['uci', 'set', f'uhttpd.routekit.cert={_get(cfg, "cert")}'],
        ['uci', 'set', f'uhttpd.routekit.key={_get(cfg, "key")}'],
        ['uci', 'set', 'uhttpd.routekit.redirect_https=0'],
        ['uci', 'commit', 'uhttpd'],
    ):
        _run(cmd)


def _remove_ip(cfg):
    ip = _ipv4(cfg.get('ip'))
    if not ip:
        return
    dev = _get(cfg, 'lan_device')
    for line in _out(['ip', '-o', '-4', 'addr', 'show', 'dev', dev]).splitlines():
        parts = line.split()
        if len(parts) > 3 and parts[3].split('/', 1)[0] == ip:
            _run(['ip', 'addr', 'del', parts[3], 'dev', dev])


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
