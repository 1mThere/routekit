# RouteKit

RouteKit is a small OpenWrt-oriented Python orchestrator.

Core rules:

- no per-device policies;
- no user portal in core;
- no OpenVPN/WireGuard/sing-box config editing in core;
- everything optional is a module;
- all traffic policies are global for the configured LAN scope;
- default state is direct traffic.

## Install on OpenWrt

```sh
apk add python3 curl ca-bundle
cd /tmp
curl -L https://github.com/YOUR_USER/routekit/archive/refs/heads/main.tar.gz -o routekit.tar.gz
tar -xzf routekit.tar.gz
cd routekit-main
python3 install.py
```

For an updateable checkout:

```sh
apk add python3 git curl ca-bundle
git clone https://github.com/YOUR_USER/routekit.git /opt/routekit
python3 /opt/routekit/install.py --source /opt/routekit
```

Then:

```sh
rk init
rk module list
rk doctor
```

## Basic global domain VPN setup

RouteKit does not configure VPN clients. First create a normal OpenWrt network interface, for example `vpnclient`, using OpenVPN/WireGuard/sing-box/etc.

Then configure the provider:

```sh
rk module enable provider_openwrt_iface
rk module set provider_openwrt_iface interface vpnclient
rk module set provider_openwrt_iface table_name rk_vpn
rk module set provider_openwrt_iface table_id 1001
rk module set provider_openwrt_iface mark 0x00520000
rk module set provider_openwrt_iface mark_mask 0x00ff0000
```

Enable global domain routing:

```sh
rk module enable domain_vpn
rk module set domain_vpn provider provider_openwrt_iface
rk domain add youtube.com googlevideo.com ytimg.com
rk apply
```

All LAN clients are treated the same. There are no per-device controls.

## Optional portal module

The portal module is optional and global. It is not a per-user control panel.

```sh
rk module enable portal_static
rk module set portal_static domain v.be
rk module set portal_static ip 192.168.1.2
rk apply
```

## Future modules

`zapret` should be a separate module. It should not be built into core.
