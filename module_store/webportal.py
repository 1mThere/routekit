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
    _write(home / 'cgi-bin' / 'luci', _luci_redirect(), 0o755)

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
    body = '\n'.join(tiles) or '<section class="tile empty"><h2>Модули не подключены</h2><p>Включи нужные модули через rk enable.</p></section>'
    return f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>RouteKit</title>
<style>
:root{{color-scheme:dark;--bg:#070a0f;--panel:#111827;--panel2:#0f172a;--text:#e5edf7;--muted:#93a4b8;--line:#263244;--accent:#7dd3fc;--ok:#86efac;--err:#fca5a5}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;background:radial-gradient(circle at 20% 0%,#12304a 0,#070a0f 38%,#05070b 100%);color:var(--text);font-family:Inter,Arial,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:34px 18px 46px}}
header{{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:22px}}
h1{{margin:0;font-size:42px;letter-spacing:-1.2px}}
.sub{{margin:8px 0 0;color:var(--muted)}}
.badge{{border:1px solid var(--line);border-radius:999px;padding:8px 12px;background:rgba(17,24,39,.72);color:var(--muted);white-space:nowrap}}
.grid{{display:grid;gap:16px}}
.tile,section{{background:linear-gradient(180deg,rgba(17,24,39,.94),rgba(15,23,42,.94));border:1px solid var(--line);border-radius:18px;padding:18px 20px;box-shadow:0 16px 40px rgba(0,0,0,.22)}}
h2{{margin:0 0 12px;font-size:22px}}
p{{line-height:1.45}}
label{{display:block;margin:12px 0 8px;color:var(--muted)}}
select,button{{width:100%;max-width:420px;border:1px solid var(--line);border-radius:12px;background:#0b1220;color:var(--text);padding:11px 12px;font-size:15px}}
button{{margin-top:12px;background:linear-gradient(135deg,#0ea5e9,#2563eb);border:0;font-weight:700;cursor:pointer}}
pre{{white-space:pre-wrap;background:#070a0f;border:1px solid var(--line);border-radius:12px;padding:12px;color:#cbd5e1}}
.status{{color:var(--muted)}}
.status.ok{{color:var(--ok)}}
.status.err{{color:var(--err)}}
.footer{{margin-top:16px;color:var(--muted);font-size:13px}}
a{{color:var(--accent)}}
</style>
</head>
<body>
<main>
<header>
<div><h1>RouteKit</h1><p class="sub">Локальная панель управления маршрутизацией</p></div>
<div class="badge" id="api-state">API: проверка...</div>
</header>
<div class="grid">
{body}
</div>
<p class="footer">LuCI остаётся на <a href="http://192.168.1.1/cgi-bin/luci/">192.168.1.1</a></p>
</main>
<script>
fetch('/cgi-bin/routekit-user',{{cache:'no-store'}})
  .then(r => r.json())
  .then(d => {{ document.getElementById('api-state').textContent = d.ok ? 'API: OK' : 'API: ошибка'; }})
  .catch(() => {{ document.getElementById('api-state').textContent = 'API: не отвечает'; document.getElementById('api-state').style.color = 'var(--err)'; }});
</script>
</body>
</html>
'''


def _user_api(users_dir):
    return f'''#!/usr/bin/python3
import json
import os
from pathlib import Path
users_dir = Path({users_dir!r})
users_dir.mkdir(parents=True, exist_ok=True)
print('Content-Type: application/json; charset=utf-8')
print('Cache-Control: no-store')
print()
print(json.dumps({{'ok': True, 'remote_addr': os.environ.get('REMOTE_ADDR', ''), 'method': os.environ.get('REQUEST_METHOD', 'GET')}}, ensure_ascii=False))
'''


def _luci_redirect():
    return '''#!/usr/bin/python3
print('Status: 302 Found')
print('Location: /')
print('Cache-Control: no-store')
print()
'''
