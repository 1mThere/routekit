import json
from pathlib import Path

PRIORITY = 20
DEFAULTS = {
    'provider': 'openvpn',
    'providers': ['openvpn', 'wireguard', 'vless'],
    'list_path': '/etc/routekit/lists/standard.txt',
    'users_dir': '/etc/routekit/users',
    'dst_set': 'rk_vpn_dst4',
    'standard_src_set': 'rk_vpn_standard_src4',
    'all_src_set': 'rk_vpn_all_src4',
    'chain_name': 'rk_vpn_prerouting',
    'mark': '0x00520000',
    'mark_mask': '0x00ff0000',
}


def _write(path, data, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding='utf-8') if path.exists() else None
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


def _domains(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
        d = line.strip().lower()
        if d and not d.startswith('#'):
            out.append(d)
    return sorted(set(out))


def _users(path):
    root = Path(path)
    if not root.exists():
        return []
    out = []
    for p in root.glob('*.json'):
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        ip = str(data.get('ip') or '').strip()
        mode = str(data.get('mode') or 'direct').strip()
        if ip and mode in ('direct', 'standard', 'vpn_all'):
            out.append(data)
    return out


def _set_block(name, ips=None):
    ips = sorted(set(ips or []))
    elements = ''
    if ips:
        elements = '\n                elements = { ' + ', '.join(ips) + ' }'
    return f'''        set {name} {{
                type ipv4_addr
                flags interval
                auto-merge{elements}
        }}'''


def _add_tile(core, html):
    if not hasattr(core, 'portal_tiles'):
        core.portal_tiles = []
    core.portal_tiles.append(html)


def _tile(providers):
    options = ''.join(f'<option value="{p}">{p}</option>' for p in providers)
    return f'''<section class="tile" id="vpn-tile">
<h2>VPN</h2>
<form id="vpn-form">
<label>Режим
<select name="mode">
<option value="direct">напрямую</option>
<option value="standard">список через VPN</option>
<option value="vpn_all">всё через VPN</option>
</select>
</label>
<label>Протокол
<select name="provider">
{options}
</select>
</label>
<button type="submit">Сохранить</button>
<p class="status" id="vpn-status"></p>
</form>
<script>
(() => {{
  const api = '/cgi-bin/routekit-vpn';
  const form = document.getElementById('vpn-form');
  const status = document.getElementById('vpn-status');
  function setStatus(text, cls) {{ status.textContent = text; status.className = 'status ' + (cls || ''); }}
  function fill(data) {{
    if (!data.ok) {{ setStatus(data.error || 'Ошибка', 'err'); return; }}
    if (form.mode.querySelector('option[value="' + data.mode + '"]')) form.mode.value = data.mode;
    if (form.provider.querySelector('option[value="' + data.provider + '"]')) form.provider.value = data.provider;
    setStatus(data.saved ? 'Сохранено' : '', data.saved ? 'ok' : '');
  }}
  fetch(api, {{cache:'no-store'}}).then(r => r.json()).then(fill).catch(e => setStatus('API не ответил', 'err'));
  form.addEventListener('submit', e => {{
    e.preventDefault();
    setStatus('Сохранение...');
    fetch(api, {{method:'POST', body:new URLSearchParams(new FormData(form))}})
      .then(r => r.json()).then(fill).catch(e => setStatus('Не сохранилось', 'err'));
  }});
}})();
</script>
</section>'''


def _api(users_dir, default_provider, providers):
    providers_json = json.dumps(providers)
    return f'''#!/usr/bin/python3
import json
import os
import re
import urllib.parse
from pathlib import Path

USERS_DIR = Path({users_dir!r})
PROVIDERS = {providers_json}
MODES = {{'direct', 'standard', 'vpn_all'}}


def respond(data):
    print('Content-Type: application/json; charset=utf-8')
    print()
    print(json.dumps(data, ensure_ascii=False))


def mac_for_ip(ip):
    try:
        for line in Path('/proc/net/arp').read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4 and parts[0] == ip:
                return parts[3].lower()
    except Exception:
        return ''
    return ''


def uid_for(ip, mac):
    raw = mac.replace(':', '_') if mac else ip
    return re.sub(r'[^a-zA-Z0-9_]+', '_', raw)


def read_post():
    length = int(os.environ.get('CONTENT_LENGTH') or '0')
    body = os.read(0, length).decode(errors='ignore') if length else ''
    return urllib.parse.parse_qs(body)


ip = os.environ.get('REMOTE_ADDR', '')
mac = mac_for_ip(ip)
uid = uid_for(ip, mac)
USERS_DIR.mkdir(parents=True, exist_ok=True)
path = USERS_DIR / (uid + '.json')
try:
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {{}}
except Exception:
    data = {{}}
data.setdefault('id', uid)
data['ip'] = ip
data['mac'] = mac
data.setdefault('mode', 'direct')
data.setdefault('provider', {default_provider!r})
saved = False
if os.environ.get('REQUEST_METHOD') == 'POST':
    form = read_post()
    mode = (form.get('mode') or [''])[0]
    provider = (form.get('provider') or [''])[0]
    if mode in MODES:
        data['mode'] = mode
    if provider in PROVIDERS:
        data['provider'] = provider
    saved = True
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
respond({{'ok': True, 'mode': data['mode'], 'provider': data['provider'], 'saved': saved}})
'''


def _web_home(core):
    return Path(core.config.get('modules', {}).get('webportal', {}).get('home', '/www-routekit'))


def enable(core, cfg):
    print('vpn module adds a VPN tile to the web portal.')
    cfg['provider'] = input(f'provider [{cfg.get("provider", "openvpn")}]: ').strip() or cfg.get('provider', 'openvpn')


def render(core, cfg):
    providers = cfg.get('providers') or ['openvpn', 'wireguard', 'vless']
    _add_tile(core, _tile(providers))
    home = _web_home(core)
    _write(home / 'cgi-bin' / 'routekit-vpn', _api(cfg['users_dir'], cfg.get('provider', providers[0]), providers), 0o755)

    domains = _domains(cfg['list_path'])
    users = _users(cfg['users_dir'])
    dnsmasq_dir = Path(core.config['dnsmasq_confdir'])
    fw4_dir = Path(core.config['fw4_post_dir'])
    changed = False

    dns_lines = [f'nftset=/{d}/4#inet#fw4#{cfg["dst_set"]}' for d in domains]
    changed |= _write(dnsmasq_dir / 'routekit-vpn.conf', '\n'.join(dns_lines) + ('\n' if dns_lines else ''))

    standard_ips = [u['ip'] for u in users if u.get('mode') == 'standard']
    all_ips = [u['ip'] for u in users if u.get('mode') == 'vpn_all']
    lan = core.config.get('lan_iface', 'br-lan')
    nft = f'''table inet fw4 {{
{_set_block(cfg['dst_set'])}

{_set_block(cfg['standard_src_set'], standard_ips)}

{_set_block(cfg['all_src_set'], all_ips)}

        chain {cfg['chain_name']} {{
                type filter hook prerouting priority -155; policy accept;
                meta mark & {cfg['mark_mask']} != 0 return
                iifname "{lan}" ip saddr @{cfg['all_src_set']} meta mark set meta mark & 0xff00ffff | {cfg['mark']}
                iifname "{lan}" ip saddr @{cfg['standard_src_set']} ip daddr @{cfg['dst_set']} meta mark set meta mark & 0xff00ffff | {cfg['mark']}
        }}
}}
'''
    changed |= _write(fw4_dir / '40-routekit-vpn.nft', nft)
    return ['firewall', 'dnsmasq'] if changed else []


def status(core, cfg):
    users = _users(cfg['users_dir'])
    return {
        'provider': cfg.get('provider'),
        'domains': len(_domains(cfg['list_path'])),
        'users': len(users),
    }
