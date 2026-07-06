# RouteKit

RouteKit is a Python orchestrator for OpenWrt.

Core is intentionally small:

- no per-device policies;
- no per-user settings;
- no built-in web portal;
- no built-in OpenVPN logic;
- no built-in zapret logic;
- default traffic is direct;
- every feature is a module.

The core only installs `rk`, stores config, downloads enabled modules, and runs the apply lifecycle.

## Install on OpenWrt

```sh
apk add python3 curl ca-bundle git tar gzip
curl -L https://github.com/1mThere/routekit/archive/refs/heads/main.tar.gz -o /tmp/routekit.tar.gz
rm -rf /tmp/routekit-main
tar -xzf /tmp/routekit.tar.gz -C /tmp
python3 /tmp/routekit-main/install.py
rk init
```

After this only the core is installed.

## Enable modules

```sh
rk enable webportal
rk enable vpn
rk enable openvpn
```

Dependency order:

```text
webportal -> vpn -> openvpn
```

`rk enable webportal` asks for a domain. Default: `v.be`.

`rk enable vpn` refuses to run before `webportal`.

`rk enable openvpn` refuses to run before `vpn`, then asks for an OpenVPN config file path or URL. It is a module, not core behavior.

`rk enable zapret` is intentionally not implemented yet.

## Global domain VPN

There are no device profiles. The VPN module applies globally to LAN traffic matching the domain list.

```sh
rk domain add youtube.com googlevideo.com ytimg.com x.com twitter.com twimg.com
rk apply
```

## Lifecycle

On `rk apply` the core calls enabled modules in stages:

```text
preflight -> render -> service restart -> apply -> status
```

Modules can prepare other software first. The wrapper is applied after modules render their parts.

## Update

If installed from `/opt/routekit` git checkout:

```sh
rk self update
```

If installed from tarball, download the new archive and run `install.py` again. Existing `/etc/routekit/config.json` is preserved.
