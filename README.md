# RouteKit

RouteKit is a Python orchestrator for OpenWrt.

The core installs `rk`, stores config, downloads enabled modules, and runs the apply lifecycle. Features live in modules.

## Install on OpenWrt

```sh
apk add python3 curl ca-bundle git tar gzip
curl -L https://github.com/1mThere/routekit/archive/refs/heads/main.tar.gz -o /tmp/routekit.tar.gz
rm -rf /tmp/routekit-main
tar -xzf /tmp/routekit.tar.gz -C /tmp
python3 /tmp/routekit-main/install.py
rk init
```

## Update

```sh
rk update
```

Update downloaded enabled modules:

```sh
rk modules update
```

Update one module:

```sh
rk modules update webportal
```

## Modules

```sh
rk enable gateway
rk enable webportal
rk enable vpn
rk enable openvpn
```

Dependency order:

```text
gateway -> webportal -> vpn -> provider modules
```

`gateway` owns the base LAN client path: LAN firewall zone, WAN firewall zone, masquerading, IPv4 forwarding, and LAN-to-WAN forwarding. It is intentionally separate from `vpn`; direct client internet must not depend on a VPN provider.

`webportal` creates the local portal and lets enabled modules insert their own tiles.

`vpn` inserts a VPN tile only when the VPN module is enabled. It does not ask for a protocol during `rk enable vpn`. It detects enabled provider modules, for example `openvpn`. If no provider module is enabled, the portal tile says that providers were not found.

Provider modules such as `openvpn`, `wireguard`, `vless`, `xray`, or `sing-box` prepare their own tunnel/runtime resources.

## VPN standard list

The standard list accepts domains, subdomains through their parent domain, IPv4 addresses, and IPv4 CIDR ranges.

```sh
rk vpn stlist add youtube.com googlevideo.com 1.1.1.1 8.8.8.0/24
rk vpn stlist list
rk vpn stlist del youtube.com
rk vpn stlist replace example.com 9.9.9.9
rk apply
```

## Lifecycle

On `rk apply` the core calls enabled modules in stages:

```text
preflight -> render -> service reload/restart -> apply
```

Modules can prepare software first. RouteKit applies generated DNS, firewall, portal, and routing wrappers after modules render their parts.

## License

MIT
