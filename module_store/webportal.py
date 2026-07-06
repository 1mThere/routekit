from pathlib import Path
from subprocess import run, PIPE

PRIORITY = 1000
DEFAULTS = {
    'domain': 'v.be',
    'ip': '192.168.1.2',
    'prefixlen': 32,
    'home': '/www-routekit',
    'lan_device': 'br-lan',
    'lan_ip': 'auto',
    'users_dir': '/etc/routekit/users',
    'hotplug': '/etc/hotplug.d/iface/90-routekit-webportal-ip',
}


def _run(argv, check=False, capture=False):
    if capture:
        return run(argv, check=check, text=True, stdout=PIPE, stderr=PIPE)
    return run(argv, check=check)


def _out(argv):
    p = _run(argv, capture=True)
    if p.returncode != 0:
        return ''
    return p.stdout.strip()


def _write(path, data, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = None
    if path.exists():
        try:
            old = path.read_text(encoding='utf-8')
        except Exception:
            old = None
    changed = old != data
    if changed:
        path.write_text(data, encoding='utf-8')
    if mode is not None:
        try:
            old_mode = path.stat().st_mode & 0o777
        except Exception:
            old_mode = None
        if old_mode != mode:
            path.chmod(mode)
            changed = True
    return changed


def _ask(prompt, default):
    value = input(f'{prompt} [{default}]: ').strip()
    return value or default


def enable(core, cfg):
    cfg['domain'] = _ask('portal domain', cfg.get('domain', 'v.be'))
    cfg['ip'] = _ask('portal ip', cfg.get('ip', '192.168.1.2'))
    cfg['home'] = cfg.get('home', '/www-routekit')
    cfg['users_dir'] = cfg.get('users_dir', '/etc/routekit/users')


def _lan_ip(cfg):
    if cfg.get('lan_ip') and cfg.get('lan_ip') != 'auto':
        return cfg['lan_ip']
    uci_ip = _out(['uci', '-q', 'get', 'network.lan.ipaddr'])
    return uci_ip or '192.168.1.1'


def _portal_prefixlen(cfg):
    return 32


def _ensure_dnsmasq_confdir(path):
    current = _out(['uci', '-q', 'get', 'dhcp.@dnsmasq[0].confdir'])
    if path in current.splitlines():
        return False
    _run(['uci', 'add_list', f'dhcp.@dnsmasq[0].confdir={path}'])
    _run(['uci', 'commit', 'dhcp'])
    return True


def _user_api(users_dir):
    template = r'''#!/usr/bin/python3
import json
import os
import re
from pathlib import Path

USERS_DIR = Path(__USERS_DIR__)
DEFAULT_MODE = 'direct'


def respond(data, status='200 OK'):
    print('Status: ' + status)
    print('Content-Type: application/json; charset=utf-8')
    print('Cache-Control: no-store')
    print()
    print(json.dumps(data, ensure_ascii=False))


def mac_for_ip(ip):
    try:
        for line in Path('/proc/net/arp').read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4 and parts[0] == ip:
                mac = parts[3].lower()
                if mac != '00:00:00:00:00:00':
                    return mac
    except Exception:
        pass
    return ''


def safe_id(ip, mac):
    if mac:
        return re.sub(r'[^a-z0-9_]+', '_', mac.lower().replace(':', '_'))
    return re.sub(r'[^0-9a-zA-Z_]+', '_', ip)


def user_file(uid):
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    return USERS_DIR / (uid + '.json')


def load_user(path, uid, ip, mac):
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            data = {}
    data.setdefault('id', uid)
    data['ip'] = ip
    data['mac'] = mac
    data.setdefault('mode', DEFAULT_MODE)
    return data


def save_user(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    ip = os.environ.get('REMOTE_ADDR', '')
    mac = mac_for_ip(ip)
    uid = safe_id(ip, mac)
    path = user_file(uid)
    user = load_user(path, uid, ip, mac)
    if not path.exists():
        save_user(path, user)
    respond({'ok': True, 'id': uid})


try:
    main()
except Exception as e:
    respond({'ok': False, 'error': str(e)}, '500 Internal Server Error')
'''
    return template.replace('__USERS_DIR__', repr(users_dir))


def _index_html(tiles):
    body = '\n'.join(tiles)
    if not body:
        body = '<section class="tile"><h2>Модули не подключены</h2></section>'
    return '''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RouteKit</title>
<style>
html{background:#0b0d10;color:#e7eaf0;font-family:Arial,sans-serif}
body{max-width:960px;margin:38px auto;padding:0 18px;font-size:16px}
h1{margin:0 0 18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.tile{background:#11151b;border:1px solid #2a303a;border-radius:12px;padding:18px 20px}
.tile h2{margin:0 0 14px}
label{display:block;margin:12px 0}
select{width:100%;box-sizing:border-box;margin-top:6px;padding:10px;border-radius:8px;background:#080b0f;color:#e7eaf0;border:1px solid #303744}
button{padding:11px 16px;border-radius:8px;border:1px solid #6f8cff;background:#496ee8;color:white;font-size:16px}
.status{min-height:22px;color:#9aa4b2}
.ok{color:#d9ffe3}
.err{color:#ffdada}
</style>
</head>
<body>
<h1>RouteKit</h1>
<main class="grid">
__TILES__
</main>
<script>fetch('/cgi-bin/routekit-user',{cache:'no-store'}).catch(()=>{});</script>
</body>
</html>
'''.replace('__TILES__', body)


def render(core, cfg):
    users_dir = Path(cfg.get('users_dir', '/etc/routekit/users'))
    users_dir.mkdir(parents=True, exist_ok=True)

    changed = False
    dnsmasq_dir = Path(core.config['dnsmasq_confdir'])
    dnsmasq_dir.mkdir(parents=True, exist_ok=True)
    changed |= _ensure_dnsmasq_confdir(str(dnsmasq_dir))
    changed |= _write(dnsmasq_dir / 'routekit-webportal.conf', f'address=/{cfg["domain"]}/{cfg["ip"]}\n')

    home = Path(cfg['home'])
    cgi = home / 'cgi-bin'
    cgi.mkdir(parents=True, exist_ok=True)
    tiles = list(getattr(core, 'portal_tiles', []))
    _write(home / 'index.html', _index_html(tiles))
    _write(cgi / 'routekit-user', _user_api(str(users_dir)), 0o755)
    return ['dnsmasq'] if changed else []


def _runtime_cleanup_ip(ip, keep_prefixlen, dev):
    _run(['ip', '-4', 'addr', 'flush', 'dev', dev, 'to', f'{ip}/32'])


def _runtime_add_ip(ip, prefixlen, dev):
    addr = f'{ip}/{prefixlen}'
    _run(['ip', 'addr', 'replace', addr, 'dev', dev])


def _write_hotplug(cfg):
    ip = cfg['ip']
    dev = cfg.get('lan_device', 'br-lan')
    prefixlen = _portal_prefixlen(cfg)
    path = cfg.get('hotplug', '/etc/hotplug.d/iface/90-routekit-webportal-ip')
    _write(path, f'''#!/bin/sh
[ "$ACTION" = "ifup" ] || [ "$ACTION" = "ifupdate" ] || exit 0
[ "$DEVICE" = "{dev}" ] || [ "$INTERFACE" = "lan" ] || exit 0
ip -4 addr flush dev "{dev}" to "{ip}/32" 2>/dev/null
ip addr replace "{ip}/{prefixlen}" dev "{dev}" 2>/dev/null
exit 0
''', 0o755)


def _cleanup_old_network():
    if _out(['uci', '-q', 'show', 'network.routekit_portal']):
        _run(['uci', '-q', 'delete', 'network.routekit_portal'])
        _run(['uci', 'commit', 'network'])


def _bind_uhttpd(cfg):
    portal_ip = cfg['ip']
    lan_ip = _lan_ip(cfg)
    home = cfg['home']
    before = _out(['uci', 'show', 'uhttpd'])

    _run(['uci', '-q', 'delete', 'uhttpd.routekit'])
    _run(['uci', 'set', 'uhttpd.routekit=uhttpd'])
    _run(['uci', 'add_list', f'uhttpd.routekit.listen_http={portal_ip}:80'])
    _run(['uci', 'set', f'uhttpd.routekit.home={home}'])
    _run(['uci', 'set', 'uhttpd.routekit.cgi_prefix=/cgi-bin'])
    _run(['uci', 'set', 'uhttpd.routekit.redirect_https=0'])

    _run(['uci', '-q', 'delete', 'uhttpd.main.listen_http'])
    _run(['uci', '-q', 'delete', 'uhttpd.main.listen_https'])
    _run(['uci', 'add_list', f'uhttpd.main.listen_http={lan_ip}:80'])
    _run(['uci', 'add_list', f'uhttpd.main.listen_https={lan_ip}:443'])

    after = _out(['uci', 'show', 'uhttpd'])
    if before != after:
        _run(['uci', 'commit', 'uhttpd'])
        return True
    return False


def apply(core, cfg):
    ip = cfg['ip']
    lan_device = cfg.get('lan_device', 'br-lan')
    prefixlen = _portal_prefixlen(cfg)

    _runtime_cleanup_ip(ip, prefixlen, lan_device)
    _runtime_add_ip(ip, prefixlen, lan_device)
    _write_hotplug(cfg)
    _cleanup_old_network()
    if _bind_uhttpd(cfg):
        _run(['/etc/init.d/uhttpd', 'restart'])


def status(core, cfg):
    users_dir = Path(cfg.get('users_dir', '/etc/routekit/users'))
    users = len(list(users_dir.glob('*.json'))) if users_dir.exists() else 0
    return {
        'domain': cfg.get('domain'),
        'ip': cfg.get('ip'),
        'prefixlen': _portal_prefixlen(cfg),
        'home': cfg.get('home'),
        'users': users,
        'luci': _lan_ip(cfg),
    }
