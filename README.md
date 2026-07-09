# RouteKit

RouteKit is a small Python orchestrator for OpenWrt router routing modules.

Current tested target: OpenWrt on `mediatek/filogic`, especially GL.iNet GL-MT3000. OpenWrt builds with `apk` are the main target.

## What it does

RouteKit installs one command:

```sh
rk
```

The core stores config in `/etc/routekit/config.json`, downloads enabled modules to `/var/lib/routekit/modules`, renders DNS/firewall/web files, and applies runtime routing.

Modules are separate:

```text
webportal -> vpn -> openvpn
```

`webportal` creates a local panel.

`vpn` adds the VPN mode tile to the panel and manages the standard list.

`openvpn` installs OpenVPN dependencies, imports a `.ovpn` client config, starts the tunnel, and creates a marked routing table for VPN traffic.

## Expected URLs

After `webportal` is configured with `domain=v.be` and `ip=192.168.1.2`:

```text
http://v.be        -> RouteKit panel
http://192.168.1.1 -> LuCI
```

RouteKit is served from `/www-routekit`. LuCI stays on `/www`.

## Fresh install

Install base packages:

```sh
apk update
apk add python3 curl ca-bundle tar gzip
```

Install RouteKit:

```sh
curl -L https://github.com/1mThere/routekit/archive/refs/heads/main.tar.gz -o /tmp/routekit.tar.gz
rm -rf /tmp/routekit-main
tar -xzf /tmp/routekit.tar.gz -C /tmp
python3 /tmp/routekit-main/install.py
rk init
```

The installer creates `/etc/routekit/lists/standard.txt`. If the list is empty, it downloads a default standard VPN list from:

```text
https://antifilter.download/list/domains.lst
https://antifilter.download/list/urls.lst
https://antifilter.download/list/allyouneed.lst
https://community.antifilter.download/list/domains.lst
https://community.antifilter.download/list/community.lst
https://raw.githubusercontent.com/barl0g/foreign-geo-blocklist-russia/main/domains.txt
```

## Configure web portal

Enable `webportal`:

```sh
rk enable webportal
```

Use these answers for a normal GL-MT3000 LAN setup:

```text
portal domain [v.be]:
portal ip []: 192.168.1.2
```

Do not use `192.168.1.1` as the RouteKit portal IP. `192.168.1.1` must stay LuCI.

## Upload OpenVPN config

From Windows PowerShell:

```powershell
scp -O .\client.ovpn root@192.168.1.1:/root/client.ovpn
```

Check on the router:

```sh
ls -la /root/client.ovpn
head -n 5 /root/client.ovpn
```

## Enable VPN modules

Enable the panel VPN controller:

```sh
rk enable vpn
```

Enable OpenVPN provider:

```sh
rk enable openvpn
```

Use these answers:

```text
OpenVPN config file path or URL: /root/client.ovpn
OpenWrt network interface [vpnclient]:
VPN device, or auto [auto]:
```

Apply everything:

```sh
rk apply
rk doctor
```

`openvpn` automatically tries to install:

```text
openvpn-openssl
kmod-tun
```

If `openvpn-openssl` is not available, it tries `openvpn-mbedtls`.

## Verify

From the router:

```sh
rk doctor
ls -la /www-routekit/cgi-bin
wget -qO- --proxy=off http://192.168.1.1/ | head
wget -qO- --proxy=off http://192.168.1.2/ | head
wget -qO- --proxy=off http://v.be/cgi-bin/routekit-vpn
```

Expected important parts:

```text
[openvpn] enabled=True downloaded=True
  device: tun0
  gateway: 10.8.0.1

[vpn] enabled=True downloaded=True
  providers: openvpn
  ready: openvpn

[webportal] enabled=True downloaded=True
  domain: v.be
  ip: 192.168.1.2
  home: /www-routekit
```

The RouteKit CGI directory must contain:

```text
/www-routekit/cgi-bin/routekit-user
/www-routekit/cgi-bin/routekit-vpn
```

## Use the portal

Open:

```text
http://v.be
```

Modes:

```text
напрямую
стандартный список через VPN
всё через VPN
```

If only one provider is enabled, the portal does not show a protocol selector.

## Standard VPN list

List:

```sh
rk vpn stlist list
```

Add entries:

```sh
rk vpn stlist add youtube.com googlevideo.com 1.1.1.1 8.8.8.0/24
rk apply
```

Delete entries:

```sh
rk vpn stlist del youtube.com
rk apply
```

Replace the whole list:

```sh
rk vpn stlist replace example.com 9.9.9.9
rk apply
```

The list accepts:

```text
domain names
IPv4 addresses
IPv4 CIDR ranges
```

## Update

Update RouteKit core and enabled modules:

```sh
rk update
```

`rk update` does not apply config. Apply separately:

```sh
rk apply
```

Update and apply in one command:

```sh
rk update --apply
```

Update one module only:

```sh
rk modules update vpn
rk apply
```

## Uninstall

```sh
rk uninstall
```

This removes RouteKit files, RouteKit DNS/firewall snippets, the portal webroot, and the `rk` command. It tries to restore LuCI/uhttpd state.

## Troubleshooting

### `routekit-vpn` returns 404

Run:

```sh
rk doctor
ls -la /www-routekit/cgi-bin
rk modules update vpn
rk apply
ls -la /www-routekit/cgi-bin
```

If `/www-routekit/cgi-bin/routekit-vpn` is missing after that, the `vpn` module did not render.

### Browser still shows old portal

Use a hard reload:

```text
Ctrl+F5
```

### OpenVPN is not ready

Run:

```sh
logread -e openvpn | tail -n 80
ip -4 addr show dev tun0
ip route show table rk_openvpn
```

### LuCI opens instead of RouteKit

Check that RouteKit uses a separate IP:

```sh
uci show uhttpd | grep -E 'main|routekit|listen_http|home'
ip -4 addr show dev br-lan
cat /etc/dnsmasq.d/routekit-webportal.conf
```

Expected:

```text
uhttpd.main.listen_http='192.168.1.1:80'
uhttpd.main.home='/www'
uhttpd.routekit.listen_http='192.168.1.2:80'
uhttpd.routekit.home='/www-routekit'
address=/v.be/192.168.1.2
```

## Files

```text
/usr/bin/rk
/usr/lib/routekit/routekit
/var/lib/routekit/modules
/etc/routekit/config.json
/etc/routekit/lists/standard.txt
/etc/routekit/users
/www-routekit
```

## License

MIT
