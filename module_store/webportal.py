import re
import shutil
from pathlib import Path
from subprocess import run, PIPE

PRIORITY = 1000
DEFAULTS = {
    'domain': 'v.be',
    'ip': 'auto',
    'port': 80,
    'home': '/www',
    'lan_device': 'br-lan',
    'lan_ip': 'auto',
    'users_dir': '/etc/routekit/users',
    'hotplug': '/etc/hotplug.d/iface/90-routekit-webportal-ip',
    'uhttpd_backup': '/etc/routekit/backups/uhttpd.before-webportal',
    'www_index_backup': '/etc/routekit/backups/www-index.before-webportal',
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


def _remove(path):
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return True
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _plain_ip(value, fallback='192.168.1.1'):
    value = str(value or '').strip()
    if not value or value == 'auto':
        return fallback
    match = re.search(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)', value)
    if match:
        return match.group(0)
    return fallback


def _ask(prompt, default):
    value = input(f'{prompt} [{default}]: ').strip()
    return value or default


def _lan_ip(cfg):
    if cfg.get('lan_ip') and cfg.get('lan_ip') != 'auto':
        return _plain_ip(cfg['lan_ip'])
    ip = _plain_ip(_out(['uci', '-q', 'get', 'network.lan.ipaddr']), '')
    if ip:
        return ip
    dev = cfg.get('lan_device', 'br-lan')
    return _plain_ip(_out(['ip', '-4', 'addr', 'show', 'dev', dev]))


def _legacy_ip(cfg):
    value = str(cfg.get('ip', '')).strip()
    if value and value != 'auto':
        return _plain_ip(value, '')
    return '192.168.1.2'


def enable(core, cfg):
    cfg['domain'] = _ask('portal domain', cfg.get('domain', 'v.be'))
    cfg['ip'] = 'auto'
    cfg['port'] = 80
    cfg['home'] = '/www'
    cfg['users_dir'] = cfg.get('users_dir', '/etc/routekit/users')


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
    body = '\n'.join(tiles) or '<section class="tile"><h2>Модули не подключены</h2></section>'
    template = '''<!doctype html>
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
<main class="grid">__BODY__</main>
<script>fetch('/cgi-bin/routekit-user',{cache:'no-store'}).catch(()=>{});</script>
</body>
</html>
'''
    return template.replace('__BODY__', body)


def _backup_once(src, backup):
    src = Path(src)
    backup = Path(backup)
    if src.exists() and not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, backup)


def render(core, cfg):
    cfg['ip'] = 'auto'
    cfg['port'] = 80
    cfg['home'] = '/www'
    lan_ip = _lan_ip(cfg)
    users_dir = Path(cfg.get('users_dir', '/etc/routekit/users'))
    users_dir.mkdir(parents=True, exist_ok=True)

    dnsmasq_dir = Path(core.config['dnsmasq_confdir'])
    dnsmasq_dir.mkdir(parents=True, exist_ok=True)
    changed = _ensure_dnsmasq_confdir(str(dnsmasq_dir))
    changed |= _write(dnsmasq_dir / 'routekit-webportal.conf', f'address=/{cfg["domain"]}/{lan_ip}\n')

    _backup_once('/www/index.html', cfg.get('www_index_backup', '/etc/routekit/backups/www-index.before-webportal'))
    _write('/www/index.html', _index_html(list(getattr(core, 'portal_tiles', []))))
    _write('/www/cgi-bin/routekit-user', _user_api(str(users_dir)), 0o755)
    return ['dnsmasq', 'uhttpd']


def _runtime_cleanup_ip(ip, dev):
    if not ip:
        return
    current = _run(['ip', '-o', '-4', 'addr', 'show', 'dev', dev], capture=True)
    if current.returncode != 0:
        return
    for line in current.stdout.splitlines():
        parts = line.split()
        if 'inet' not in parts:
            continue
        addr = parts[parts.index('inet') + 1]
        if addr.split('/', 1)[0] == ip:
            _run(['ip', 'addr', 'del', addr, 'dev', dev])


def _backup_uhttpd(cfg):
    _backup_once('/etc/config/uhttpd', cfg.get('uhttpd_backup', '/etc/routekit/backups/uhttpd.before-webportal'))


def _restore_uhttpd(cfg):
    backup = Path(cfg.get('uhttpd_backup', '/etc/routekit/backups/uhttpd.before-webportal'))
    dst = Path('/etc/config/uhttpd')
    if backup.exists():
        shutil.copy2(backup, dst)
        return
    rom = Path('/rom/etc/config/uhttpd')
    if rom.exists():
        shutil.copy2(rom, dst)
        return
    _run(['uci', '-q', 'delete', 'uhttpd.routekit'])
    _run(['uci', '-q', 'set', 'uhttpd.main=uhttpd'])
    _run(['uci', '-q', 'delete', 'uhttpd.main.listen_http'])
    _run(['uci', '-q', 'delete', 'uhttpd.main.listen_https'])
    _run(['uci', 'add_list', 'uhttpd.main.listen_http=0.0.0.0:80'])
    _run(['uci', 'set', 'uhttpd.main.home=/www'])
    _run(['uci', 'set', 'uhttpd.main.cgi_prefix=/cgi-bin'])
    _run(['uci', 'set', 'uhttpd.main.redirect_https=0'])
    _run(['uci', 'commit', 'uhttpd'])


def _restore_www_index(cfg):
    backup = Path(cfg.get('www_index_backup', '/etc/routekit/backups/www-index.before-webportal'))
    if backup.exists():
        shutil.copy2(backup, '/www/index.html')


def _bind_uhttpd(cfg):
    lan_ip = _lan_ip(cfg)
    _backup_uhttpd(cfg)
    _run(['uci', '-q', 'delete', 'uhttpd.routekit'])
    _run(['uci', '-q', 'set', 'uhttpd.main=uhttpd'])
    _run(['uci', '-q', 'delete', 'uhttpd.main.listen_http'])
    _run(['uci', '-q', 'delete', 'uhttpd.main.listen_https'])
    _run(['uci', 'add_list', f'uhttpd.main.listen_http={lan_ip}:80'])
    _run(['uci', 'set', 'uhttpd.main.home=/www'])
    _run(['uci', 'set', 'uhttpd.main.cgi_prefix=/cgi-bin'])
    _run(['uci', 'set', 'uhttpd.main.redirect_https=0'])
    _run(['uci', 'set', 'uhttpd.main.rfc1918_filter=0'])
    _run(['uci', 'commit', 'uhttpd'])


def apply(core, cfg):
    dev = cfg.get('lan_device', 'br-lan')
    _runtime_cleanup_ip(_legacy_ip(cfg), dev)
    _remove(cfg.get('hotplug', '/etc/hotplug.d/iface/90-routekit-webportal-ip'))
    cfg['ip'] = 'auto'
    cfg['port'] = 80
    cfg['home'] = '/www'
    _bind_uhttpd(cfg)
    _run(['/etc/init.d/uhttpd', 'enable'])
    _run(['/etc/init.d/uhttpd', 'restart'])


def cleanup(core, cfg):
    _runtime_cleanup_ip(_legacy_ip(cfg), cfg.get('lan_device', 'br-lan'))
    _remove(cfg.get('hotplug', '/etc/hotplug.d/iface/90-routekit-webportal-ip'))
    _remove('/www/cgi-bin/routekit-user')
    _remove(Path(core.config['dnsmasq_confdir']) / 'routekit-webportal.conf')
    _restore_www_index(cfg)
    _restore_uhttpd(cfg)
    _run(['/etc/init.d/uhttpd', 'enable'])
    return ['dnsmasq', 'uhttpd']


def status(core, cfg):
    users_dir = Path(cfg.get('users_dir', '/etc/routekit/users'))
    users = len(list(users_dir.glob('*.json'))) if users_dir.exists() else 0
    lan_ip = _lan_ip(cfg)
    return {
        'domain': cfg.get('domain'),
        'ip': lan_ip,
        'port': 80,
        'home': '/www',
        'users': users,
        'url': f'http://{cfg.get("domain")}',
        'luci': f'http://{lan_ip}/cgi-bin/luci',
    }
