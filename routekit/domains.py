import re
from pathlib import Path
from urllib.parse import urlparse

DOMAIN_RE = re.compile(r'^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]*[a-z0-9])?$')


def normalize_domain(item):
    item = item.strip().lower()
    if not item or item.startswith('#'):
        return None
    if '://' in item:
        parsed = urlparse(item)
        item = parsed.netloc or parsed.path
    item = item.split('/')[0].split(':')[0]
    if item.startswith('*.'):
        item = item[2:]
    item = item.lstrip('.')
    if DOMAIN_RE.match(item):
        return item
    return None


def normalize_many(items):
    out = set()
    for item in items:
        for part in str(item).replace(',', ' ').split():
            d = normalize_domain(part)
            if d:
                out.add(d)
    return sorted(out)


def read_list(path):
    path = Path(path)
    if not path.exists():
        return []
    return normalize_many(path.read_text(encoding='utf-8', errors='ignore').splitlines())


def write_list(path, domains):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(sorted(set(domains))) + ('\n' if domains else ''), encoding='utf-8')
