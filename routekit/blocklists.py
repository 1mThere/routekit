import ipaddress
import urllib.request
from pathlib import Path

from .domains import normalize_domain

DEFAULT_STANDARD_URLS = (
    'https://antifilter.download/list/domains.lst',
    'https://antifilter.download/list/urls.lst',
    'https://antifilter.download/list/allyouneed.lst',
    'https://community.antifilter.download/list/domains.lst',
    'https://community.antifilter.download/list/community.lst',
    'https://raw.githubusercontent.com/barl0g/foreign-geo-blocklist-russia/main/domains.txt',
)

FALLBACK_STANDARD = (
    'chatgpt.com',
    'openai.com',
    'oaistatic.com',
    'cdn.oaistatic.com',
    'perplexity.ai',
    'linkedin.com',
    'truthsocial.com',
    'medium.com',
    'rutracker.org',
    'theins.ru',
    'meduza.io',
    'bbc.com',
    'bbc.co.uk',
    'discord.com',
    'discordapp.com',
    'signal.org',
    'instagram.com',
    'facebook.com',
    'x.com',
    'twitter.com',
)


def normalize_item(item):
    item = str(item or '').strip().lower()
    if not item or item.startswith('#') or item.startswith('!'):
        return None
    item = item.split('#', 1)[0].strip()
    if not item:
        return None
    if item.startswith('||') and item.endswith('^'):
        item = item[2:-1]
    if item.startswith('domain:'):
        item = item[7:]
    try:
        net = ipaddress.ip_network(item, strict=False)
        if net.version == 4:
            return str(net.network_address) if net.prefixlen == 32 else str(net)
    except Exception:
        pass
    return normalize_domain(item)


def normalize_items(items):
    out = set()
    for item in items:
        value = normalize_item(item)
        if value:
            out.add(value)
    return sorted(out)


def download_lines(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'routekit'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read().decode('utf-8', errors='ignore')
    return data.splitlines()


def fetch_default_standard_list(urls=DEFAULT_STANDARD_URLS):
    items = set()
    errors = []
    for url in urls:
        try:
            items.update(normalize_items(download_lines(url)))
        except Exception as e:
            errors.append(f'{url}: {e}')
    if not items:
        items.update(FALLBACK_STANDARD)
        errors.append('fallback standard list used')
    return sorted(items), errors


def write_default_standard_list(path, overwrite=False):
    path = Path(path)
    if path.exists() and path.read_text(encoding='utf-8', errors='ignore').strip() and not overwrite:
        return False, 0, []
    items, errors = fetch_default_standard_list()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '# RouteKit standard list',
        '# Sources:',
        *[f'# {url}' for url in DEFAULT_STANDARD_URLS],
        '',
        *items,
        '',
    ]
    path.write_text('\n'.join(lines), encoding='utf-8')
    return True, len(items), errors
