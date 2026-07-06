from pathlib import Path
from subprocess import run, PIPE

PRIORITY = 10
DEFAULTS = {
    'domain': 'v.be',
    'ip': '192.168.1.2',
    'prefixlen': 24,
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
    path.write_text(data, encoding='utf-8')
    if mode is not None:
        path.chmod(mode)


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


def _ensure_dnsmasq_confdir(path):
    _run(['uci', '-q', 'del_list', f'dhcp.@dnsmasq[0].confdir={path}'])
    _run(['uci', 'add_list', f'dhcp.@dnsmasq[0].confdir={path}'])
    _run(['uci', 'commit', 'dhcp'])


def _cgi_script(users_dir):
    template = """#!/usr/bin/env python3
import html
import json
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

USERS_DIR = Path(__USERS_DIR__)
DEFAULT_MODE = 'direct'
MODES = {'direct', 'standard', 'vpn_all'}


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
            data = json.loads(path.read_text())
        except Exception:
            data = {}
    data.setdefault('id', uid)
    data['ip'] = ip
    data['mac'] = mac
    data.setdefault('mode', DEFAULT_MODE)
    if data.get('mode') not in MODES:
        data['mode'] = DEFAULT_MODE
    return data


def save_user(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def apply_async():
    try:
        subprocess.Popen(
            ['/usr/bin/rk', 'apply'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def read_post():
    try:
        length = int(os.environ.get('CONTENT_LENGTH') or '0')
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    body = os.read(0, length).decode(errors='ignore')
    return urllib.parse.parse_qs(body)


def checked(current, value):
    return 'checked' if current == value else ''


ip = os.environ.get('REMOTE_ADDR', '')
mac = mac_for_ip(ip)
uid = safe_id(ip, mac)
path = user_file(uid)
user = load_user(path, uid, ip, mac)

if not path.exists():
    save_user(path, user)

if os.environ.get('REQUEST_METHOD') == 'POST':
    form = read_post()
    mode = (form.get('mode') or [''])[0]
    if mode in MODES:
        user['mode'] = mode
        save_user(path, user)
        apply_async()
    print('Status: 303 See Other')
    print('Location: /cgi-bin/routekit?saved=1')
    print()
    raise SystemExit

saved = 'saved=1' in os.environ.get('QUERY_STRING', '')
mode = user.get('mode', DEFAULT_MODE)

print('Content-Type: text/html; charset=utf-8')
print('Cache-Control: no-store')
print()
print(f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RouteKit</title>
<style>
html{{background:#0b0d10;color:#e7eaf0;font-family:Arial,sans-serif}}
body{{max-width:760px;margin:40px auto;padding:0 18px;font-size:16px}}
.card{{background:#11151b;border:1px solid #2a303a;border-radius:12px;padding:18px 20px;margin:14px 0}}
h1{{margin:0 0 14px}}
code{{background:#080b0f;border:1px solid #303744;border-radius:6px;padding:2px 7px}}
label{{display:block;padding:13px 0;border-top:1px solid #252b34}}
label:first-of-type{{border-top:0}}
button{{padding:11px 16px;border-radius:8px;border:1px solid #6f8cff;background:#496ee8;color:white;font-size:16px}}
.ok{{background:#102216;border:1px solid #2d7a43;color:#d9ffe3;padding:10px 12px;border-radius:8px}}
.muted{{color:#9aa4b2}}
</style>
</head>
<body>
<h1>RouteKit</h1>
{'<div class="ok">Сохранено</div>' if saved else ''}
<section class="card">
<p>IP: <code>{html.escape(ip)}</code></p>
<p>MAC: <code>{html.escape(mac or '-')}</code></p>
<p>Конфиг: <code>{html.escape(str(path))}</code></p>
</section>
<form method="post" class="card">
<h2>Режим маршрутизации</h2>
<label><input type="radio" name="mode" value="direct" {checked(mode, 'direct')}> напрямую</label>
<label><input type="radio" name="mode" value="standard" {checked(mode, 'standard')}> список через VPN</label>
<label><input type="radio" name="mode" value="vpn_all" {checked(mode, 'vpn_all')}> всё через VPN</label>
<button type="submit">Сохранить</button>
<p class="muted">Для каждого клиента создаётся отдельный конфиг. По умолчанию используется режим напрямую.</p>
</form>
</body>
</html>''')
"""
    return template.replace('__USERS_DIR__', repr(users_dir))


def render(core, cfg):
    users_dir = Path(cfg.get('users_dir', '/etc/routekit/users'))
    users_dir.mkdir(parents=True, exist_ok=True)

    dnsmasq_dir = Path(core.config['dnsmasq_confdir'])
    dnsmasq_dir.mkdir(parents=True, exist_ok=True)
    _ensure_dnsmasq_confdir(str(dnsmasq_dir))
    _write(dnsmasq_dir / 'routekit-webportal.conf', f'address=/{cfg["domain"]}/{cfg["ip"]}\n')

    home = Path(cfg['home'])
    cgi = home / 'cgi-bin'
    cgi.mkdir(parents=True, exist_ok=True)
    _write(home / 'index.html', '''<!doctype html>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=/cgi-bin/routekit">
<title>RouteKit</title>
<a href="/cgi-bin/routekit">RouteKit</a>
''')
    _write(cgi / 'routekit', _cgi_script(str(users_dir)), 0o755)
    return ['dnsmasq']


def _runtime_add_ip(ip, prefixlen, dev):
    addr = f'{ip}/{prefixlen}'
    current = _run(['ip', '-4', 'addr', 'show', 'dev', dev], capture=True)
    if current.returncode == 0 and addr in current.stdout:
        return
    _run(['ip', 'addr', 'add', addr, 'dev', dev])


def _write_hotplug(cfg):
    ip = cfg['ip']
    dev = cfg.get('lan_device', 'br-lan')
    prefixlen = int(cfg.get('prefixlen', 24))
    path = cfg.get('hotplug', '/etc/hotplug.d/iface/90-routekit-webportal-ip')
    _write(path, f'''#!/bin/sh
[ "$ACTION" = "ifup" ] || [ "$ACTION" = "ifupdate" ] || exit 0
[ "$DEVICE" = "{dev}" ] || [ "$INTERFACE" = "lan" ] || exit 0
ip -4 addr show dev "{dev}" | grep -q "{ip}/{prefixlen}" && exit 0
ip addr add "{ip}/{prefixlen}" dev "{dev}" 2>/dev/null
exit 0
''', 0o755)


def _bind_uhttpd(cfg):
    portal_ip = cfg['ip']
    lan_ip = _lan_ip(cfg)
    home = cfg['home']

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

    _run(['uci', 'commit', 'uhttpd'])


def apply(core, cfg):
    ip = cfg['ip']
    lan_device = cfg.get('lan_device', 'br-lan')
    prefixlen = int(cfg.get('prefixlen', 24))

    _runtime_add_ip(ip, prefixlen, lan_device)
    _write_hotplug(cfg)
    _bind_uhttpd(cfg)
    _run(['/etc/init.d/uhttpd', 'restart'])


def status(core, cfg):
    users_dir = Path(cfg.get('users_dir', '/etc/routekit/users'))
    users = len(list(users_dir.glob('*.json'))) if users_dir.exists() else 0
    return {
        'domain': cfg.get('domain'),
        'ip': cfg.get('ip'),
        'home': cfg.get('home'),
        'users_dir': str(users_dir),
        'users': users,
        'luci': _lan_ip(cfg),
    }
