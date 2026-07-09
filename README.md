# RouteKit

RouteKit is a small Python orchestrator for OpenWrt.

The core installs `rk`, stores config, downloads enabled modules, and runs the apply lifecycle. Features live in modules.

## Requirements

OpenWrt 25.x uses `apk`:

```sh
apk update
apk add python3 curl ca-bundle tar gzip
```

OpenWrt 23.x and older use `opkg`:

```sh
opkg update
opkg install python3 curl ca-bundle tar gzip
```

## Install

```sh
curl -L https://github.com/1mThere/routekit/archive/refs/heads/main.tar.gz -o /tmp/routekit.tar.gz
rm -rf /tmp/routekit-main
tar -xzf /tmp/routekit.tar.gz -C /tmp
python3 /tmp/routekit-main/install.py
rk init
```

The installer also creates the default VPN standard list at:

```text
/etc/routekit/lists/standard.txt
```

If the list already exists and is not empty, RouteKit keeps it.

## Clean reinstall

```sh
rk uninstall
rm -rf /tmp/routekit-main /tmp/routekit.tar.gz
curl -L https://github.com/1mThere/routekit/archive/refs/heads/main.tar.gz -o /tmp/routekit.tar.gz
tar -xzf /tmp/routekit.tar.gz -C /tmp
python3 /tmp/routekit-main/install.py
rk init
```

## Quick start: web portal + VPN + OpenVPN

Enable the local RouteKit portal:

```sh
rk enable webportal
```

Recommended values:

```text
portal domain [v.be]:
portal ip []: 192.168.1.2
```

`portal ip` must be a free LAN address. Do not use the LuCI address.

Enable the VPN panel:

```sh
rk enable vpn
```

Upload your OpenVPN config to the router:

```sh
scp -O client.ovpn root@192.168.1.1:/root/client.ovpn
```

If your SCP client does not support legacy SCP mode:

```sh
cat client.ovpn | ssh root@192.168.1.1 "cat > /root/client.ovpn"
```

Enable OpenVPN:

```sh
rk enable openvpn
```

Recommended values:

```text
OpenVPN config file path or URL: /root/client.ovpn
OpenWrt network interface [vpnclient]:
VPN device, or auto [auto]:
```

Apply everything:

```sh
rk apply
```

Expected result:

```text
http://v.be -> RouteKit portal
http://192.168.1.1 -> LuCI
http://192.168.1.1/cgi-bin/luci -> LuCI
```

## Update

Update RouteKit core and all enabled modules:

```sh
rk update
```

`rk update` does not apply config automatically.

Apply after update:

```sh
rk apply
```

Update and apply in one step:

```sh
rk update --apply
```

Update one module only:

```sh
rk modules update webportal
rk modules update vpn
rk modules update openvpn
```

## Modules

```sh
rk enable webportal
rk enable vpn
rk enable openvpn
```

Dependency order:

```text
webportal -> vpn -> provider modules
```

`webportal` creates the local portal and lets enabled modules insert their own tiles.

`vpn` inserts a VPN tile only when a VPN provider module is enabled. It detects enabled provider modules, for example `openvpn`. If there is only one provider, the portal hides the protocol selector.

`openvpn` installs OpenVPN packages automatically when possible, prepares the runtime config, starts OpenVPN, and creates the marked routing table used by `vpn`.

## VPN standard list

The standard list accepts domains, URLs, IPv4 addresses, and IPv4 CIDR ranges.

```sh
rk vpn stlist add youtube.com googlevideo.com 1.1.1.1 8.8.8.0/24
rk vpn stlist list
rk vpn stlist del youtube.com
rk vpn stlist replace example.com 9.9.9.9
rk apply
```

The default list is loaded from RKN and community blocklist sources plus a small external geo-block list for services unavailable from Russian IPs.

To force reload the default list:

```sh
rm -f /etc/routekit/lists/standard.txt
rk update
rk apply
```

## Diagnostics

```sh
rk doctor
ls -la /www-routekit/cgi-bin
wget -qO- --proxy=off http://v.be/cgi-bin/routekit-user
wget -qO- --proxy=off http://v.be/cgi-bin/routekit-vpn
logread -e uhttpd | tail -n 80
logread -e openvpn | tail -n 80
```

## Lifecycle

On `rk apply` the core calls enabled modules in stages:

```text
preflight -> render -> service reload/restart -> apply
```

Modules can prepare software first. RouteKit applies generated DNS, firewall, portal, and routing wrappers after modules render their parts.

## License

MIT
