from pathlib import Path
from subprocess import run, PIPE

PRIORITY = 10
DEFAULTS = {
    'domain': 'v.be',
    'ip': '192.168.1.2',
    'prefixlen': 24,
    'home': '/www-routekit',
    'lan_device': 'br-lan',
    'hotplug': '/etc/hotplug.d/iface/90-routekit-webportal-ip',
}


def _run(argv, check=False, capture=False):
    if capture:
        return run(argv, check=check, text=True, stdout=PIPE, stderr=PIPE)
    return run(argv, check=check)


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


def _ensure_dnsmasq_confdir(path):
    _run(['uci', '-q', 'del_list', f'dhcp.@dnsmasq[0].confdir={path}'])
    _run(['uci', 'add_list', f'dhcp.@dnsmasq[0].confdir={path}'])
    _run(['uci', 'commit', 'dhcp'])


def render(core, cfg):
    dnsmasq_dir = Path(core.config['dnsmasq_confdir'])
    dnsmasq_dir.mkdir(parents=True, exist_ok=True)
    _ensure_dnsmasq_confdir(str(dnsmasq_dir))
    _write(dnsmasq_dir / 'routekit-webportal.conf', f'address=/{cfg["domain"]}/{cfg["ip"]}\n')

    home = Path(cfg['home'])
    home.mkdir(parents=True, exist_ok=True)
    _write(home / 'index.html', f'''<!doctype html>
<meta charset="utf-8">
<title>RouteKit</title>
<style>
html{{background:#0b0d10;color:#e7eaf0;font-family:Arial,sans-serif}}
body{{max-width:760px;margin:40px auto;padding:0 18px}}
.card{{background:#11151b;border:1px solid #2a303a;border-radius:10px;padding:18px 20px}}
code{{background:#080b0f;border:1px solid #303744;border-radius:6px;padding:2px 7px}}
</style>
<h1>RouteKit</h1>
<div class="card">
<p>Core is running.</p>
<p>This portal is global. It has no per-device controls.</p>
<p>Domain: <code>{cfg['domain']}</code></p>
</div>
''')
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


def apply(core, cfg):
    ip = cfg['ip']
    home = cfg['home']
    lan_device = cfg.get('lan_device', 'br-lan')
    prefixlen = int(cfg.get('prefixlen', 24))

    _runtime_add_ip(ip, prefixlen, lan_device)
    _write_hotplug(cfg)

    _run(['uci', '-q', 'delete', 'uhttpd.routekit'])
    _run(['uci', 'set', 'uhttpd.routekit=uhttpd'])
    _run(['uci', 'set', f'uhttpd.routekit.home={home}'])
    _run(['uci', 'set', f'uhttpd.routekit.listen_http={ip}:80'])
    _run(['uci', 'set', 'uhttpd.routekit.cgi_prefix=/cgi-bin'])
    _run(['uci', 'commit', 'uhttpd'])

    _run(['/etc/init.d/uhttpd', 'restart'])


def status(core, cfg):
    return {'domain': cfg.get('domain'), 'ip': cfg.get('ip'), 'home': cfg.get('home')}
