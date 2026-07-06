from pathlib import Path

from .base import Module
from ..system import atomic_write, run


class PortalStaticModule(Module):
    name = 'portal_static'
    priority = 80
    defaults = {
        'enabled': False,
        'domain': 'v.be',
        'ip': '192.168.1.2',
        'home': '/www-routekit',
    }

    def render(self):
        cfg = self.cfg()
        dnsmasq_dir = Path(self.core.config['dnsmasq_confdir'])
        dnsmasq_file = dnsmasq_dir / 'routekit-portal.conf'
        atomic_write(dnsmasq_file, f'address=/{cfg["domain"]}/{cfg["ip"]}\n')

        home = Path(cfg['home'])
        home.mkdir(parents=True, exist_ok=True)
        atomic_write(home / 'index.html', '''<!doctype html>
<meta charset="utf-8">
<title>RouteKit</title>
<h1>RouteKit</h1>
<p>RouteKit is installed. This portal module is intentionally global and does not expose per-device controls.</p>
''')

        return ['dnsmasq']

    def apply(self):
        cfg = self.cfg()
        ip = cfg['ip']
        home = cfg['home']
        run(['uci', '-q', 'delete', 'network.routekit_portal'], check=False)
        run(['uci', 'set', 'network.routekit_portal=interface'], check=False)
        run(['uci', 'set', 'network.routekit_portal.proto=static'], check=False)
        run(['uci', 'set', 'network.routekit_portal.device=br-lan'], check=False)
        run(['uci', 'set', f'network.routekit_portal.ipaddr={ip}'], check=False)
        run(['uci', 'set', 'network.routekit_portal.netmask=255.255.255.0'], check=False)
        run(['uci', 'commit', 'network'], check=False)

        run(['uci', '-q', 'delete', 'uhttpd.routekit'], check=False)
        run(['uci', 'set', 'uhttpd.routekit=uhttpd'], check=False)
        run(['uci', 'set', f'uhttpd.routekit.home={home}'], check=False)
        run(['uci', 'set', f'uhttpd.routekit.listen_http={ip}:80'], check=False)
        run(['uci', 'set', 'uhttpd.routekit.cgi_prefix=/cgi-bin'], check=False)
        run(['uci', 'commit', 'uhttpd'], check=False)
        for svc in ('network', 'uhttpd'):
            run([f'/etc/init.d/{svc}', 'restart'], check=False)
        return []

    def status(self):
        cfg = self.cfg()
        return {'domain': cfg['domain'], 'ip': cfg['ip'], 'home': cfg['home']}
