#!/bin/sh
set -eu

rm -rf /usr/lib/routekit
rm -rf /usr/libexec/routekit
rm -rf /www-routekit
rm -f /usr/bin/rk
rm -f /usr/bin/routekit
rm -f /usr/bin/stdlist
rm -f /etc/dnsmasq.d/routekit.conf
rm -f /etc/dnsmasq.d/routekit-domain-vpn.conf
rm -f /etc/dnsmasq.d/routekit-portal.conf
rm -f /usr/share/nftables.d/ruleset-post/40-routekit.nft
rm -f /usr/share/nftables.d/ruleset-post/40-routekit-domain-vpn.nft
rm -f /etc/hotplug.d/dhcp/90-routekit-sync
rm -f /etc/hotplug.d/iface/95-routekit-route-up

uci -q delete network.routekit_portal || true
uci -q delete uhttpd.routekit || true
uci commit network || true
uci commit uhttpd || true

/etc/init.d/firewall restart || true
/etc/init.d/dnsmasq restart || true
/etc/init.d/uhttpd restart || true

echo 'old routekit runtime removed; /etc/routekit preserved if it existed'
