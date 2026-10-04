"""Capture settings and URL identity, independent of Qt and networking."""
from dataclasses import dataclass, asdict
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit, urljoin
import re


@dataclass(frozen=True)
class Settings:
    depth: int = 3
    pages: int = 500
    sites: int = 2
    connections: int = 4
    budget: int | None = None
    timeout: int = 30
    retries: int = 2
    lightweight: bool = False
    layout: str = 'original'
    template_limit_mb: int = 300

    def validate(self):
        from .size_policy import validate_mb
        validate_mb(self.template_limit_mb)
        if not (1 <= self.depth <= 3 and 1 <= self.pages <= 10000 and
                1 <= self.sites <= 4 and 1 <= self.connections <= 8):
            raise ValueError('采集参数超出允许范围')
        return dict(asdict(self), budget=None, policy_version=2)


def canonical(value, base=''):
    value = urljoin(base, value.strip()) if base else value.strip()
    p = urlsplit(value)
    if p.scheme.lower() not in ('http', 'https') or not p.hostname or p.username or p.password:
        return ''
    try:
        host = p.hostname.encode('idna').decode().lower()
        port = p.port
    except (ValueError, UnicodeError):
        return ''
    if ':' in host:
        host = '[' + host + ']'
    if port and not ((port == 80 and p.scheme == 'http') or (port == 443 and p.scheme == 'https')):
        host += ':' + str(port)
    return urlunsplit((p.scheme.lower(), host, p.path or '/', p.query, ''))


def seeds(text):
    result = []
    for value in text.splitlines():
        value = value.strip()
        if not value:
            continue
        url = canonical(value if '://' in value else 'https://' + value)
        if not url:
            raise ValueError('网址无效：' + value[:150])
        if url not in result:
            result.append(url)
    if not result or len(result) > 200:
        raise ValueError('请输入 1–200 个网址，每行一个')
    return result


def local_path(url, kind, seed):
    if url == seed:
        return 'index.html'
    p = urlsplit(url)
    ext = p.path.rsplit('/', 1)[-1].rsplit('.', 1)[-1].lower()
    ext = ext if re.fullmatch('[a-z0-9]{1,8}', ext) and '.' in p.path.rsplit('/', 1)[-1] else 'bin'
    if kind == 'page':
        ext = 'html'
    return ('pages/' if kind == 'page' else 'assets/') + sha256(url.encode()).hexdigest()[:32] + '.' + ext


def site_folder(url, task_id):
    return re.sub('[^a-zA-Z0-9.-]', '_', urlsplit(url).hostname or 'site')[:80] + '-' + task_id[:8]
