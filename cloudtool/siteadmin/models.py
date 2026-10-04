"""Site input and credential values; no UI, HTTP or persistence."""
import base64
import json
from dataclasses import dataclass, asdict
from urllib.parse import urlsplit
from ..domain_names import domain


def server_url(value):
    parts = urlsplit(value.strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('后台地址需为 http:// 或 https:// 地址，不可包含账号密码')
    if parts.query or parts.fragment or parts.path.rstrip('/') not in ('', '/login', '/sites', '/api'):
        raise ValueError('请填写后台根地址，或 /login、/sites 页面地址')
    _ = parts.port
    return f'{parts.scheme}://{parts.netloc.lower()}'


@dataclass(frozen=True)
class Credentials:
    url: str
    username: str
    password: str

    def encode(self):
        url = server_url(self.url)
        if not self.username.strip() or not self.password:
            raise ValueError('请填写后台账号和密码')
        return base64.urlsafe_b64encode(json.dumps(dict(url=url, username=self.username.strip(), password=self.password), ensure_ascii=False).encode()).decode()

    @classmethod
    def decode(cls, value):
        return cls(**json.loads(base64.urlsafe_b64decode(value)))


@dataclass(frozen=True)
class Site:
    code: str
    name: str
    primary_domain: str
    link_protocol: str = 'https'

    def body(self): return asdict(self)


def parse_sites(text, wildcard=True, protocol='https'):
    if protocol not in ('http', 'https'): raise ValueError('外链协议无效')
    if len(text) > 1024 * 1024: raise ValueError('请分批输入，文本超过 1 MB')
    names = []
    for number, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip()
        if not raw: continue
        if raw.startswith('*.'): raw = raw[2:]
        try: name = domain(raw)
        except ValueError as exc: raise ValueError(f'第 {number} 行：{exc}') from None
        if name not in names: names.append(name)
    if not 1 <= len(names) <= 1000: raise ValueError('请填写 1–1000 个不同域名，每行一个')
    return tuple(Site(n, n, ('*.' if wildcard else '') + n, protocol) for n in names)
