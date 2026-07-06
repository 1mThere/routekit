# RouteKit

RouteKit is a Python orchestrator for OpenWrt.

The core is intentionally small. It installs `rk`, stores config, downloads enabled modules, and runs the apply lifecycle. Features live in modules.

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

Update only downloaded enabled modules:

```sh
rk modules update
```

Update one module:

```sh
rk modules update webportal
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

`webportal` creates the local portal, serves the base page, and lets enabled modules insert their own tiles.

`vpn` inserts a VPN tile into the portal. It creates a per-client config under `/etc/routekit/users/` and renders routing rules from those configs.

Provider modules such as `openvpn`, `wireguard`, `vless`, `xray`, or `sing-box` are responsible for preparing their own tunnel/runtime resources. RouteKit then wraps their output through the apply lifecycle.

## Domain list

```sh
rk domain add youtube.com googlevideo.com ytimg.com x.com twitter.com twimg.com
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
