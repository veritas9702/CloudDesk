"""Validated GNAME input values; no Qt, persistence or network imports."""
import csv
import ipaddress
import re
from dataclasses import dataclass

TYPES = ('A', 'CNAME', 'MX', 'URL', 'TXT')
MODES = ('统一记录值', '逐行完整记录', '域名与记录值配对', '循环分配记录值')


from ..domain_names import domain


def domain_lines(text):
    result = tuple(dict.fromkeys(domain(v) for v in text.splitlines() if v.strip()))
    if not result or len(result) > 10000:
        raise ValueError('请输入 1–10000 个域名，每行一个')
    return result


@dataclass(frozen=True)
class Record:
    zone: str
    host: str
    kind: str
    value: str
    mx: int = 0
    ttl: int = 600

    def __post_init__(self):
        object.__setattr__(self, 'zone', domain(self.zone))
        object.__setattr__(self, 'host', self.host.strip().lower())
        object.__setattr__(self, 'kind', self.kind.strip().upper())
        object.__setattr__(self, 'value', self.value.strip())
        if self.kind != 'MX':
            object.__setattr__(self, 'mx', 0)
        if self.kind not in TYPES or not self.value or any(c in self.value for c in '\r\n\x00'):
            raise ValueError('记录类型或记录值无效')
        if not re.fullmatch(r'[@*]|(?:\*\.)?[a-z0-9_](?:[a-z0-9_.-]{0,251})', self.host):
            raise ValueError('主机记录无效：' + self.host)
        if self.kind == 'A':
            ipaddress.IPv4Address(self.value)
        if self.kind in ('CNAME', 'MX'):
            domain(self.value)
        if self.kind == 'URL' and not self.value.startswith(('https://', 'http://')):
            raise ValueError('URL 记录需要完整的 http(s) 地址')
        if self.kind == 'MX' and not 1 <= self.mx <= 50:
            raise ValueError('MX 优先级应为 1–50')
        if (self.kind != 'MX' and self.ttl != 600) or not 1 <= self.ttl <= 600:
            raise ValueError('按 GNAME 文档：普通记录 TTL 为 600，MX 可设 1–600')

    def body(self):
        return dict(ym=self.zone, zj=self.host, lx=self.kind, jlz=self.value,
                    mx=self.mx if self.kind == 'MX' else 0, ttl=self.ttl, xl='0')


def parse_records(text, mode, hosts='@', kind='A', values='', mx=5, ttl=600):
    """One parser for all four UI modes; deduplicate before touching the API."""
    if len(text) + len(values) > 10 * 1024 * 1024:
        raise ValueError('输入超过 10 MB，请分批')
    rows = [v.strip() for v in text.splitlines() if v.strip()]
    pool = [v.strip() for v in values.splitlines() if v.strip()]
    result = []
    for i, raw in enumerate(rows):
        try:
            row_hosts, row_kind, priority = hosts, kind, mx
            if mode == MODES[1]:
                parts = raw.split('|')
                if len(parts) not in (4, 5):
                    raise ValueError('格式：域名|主机记录|类型|记录值|MX优先级（可选）')
                zone, row_hosts, row_kind, value = parts[:4]
                priority = int(parts[4]) if len(parts) == 5 else mx
            elif mode == MODES[2]:
                parts = next(csv.reader([raw]))
                if len(parts) != 2:
                    raise ValueError('格式：域名,记录值；含逗号的值请用双引号包裹')
                zone, value = parts
            elif mode in (MODES[0], MODES[3]):
                if not pool or (mode == MODES[0] and len(pool) != 1):
                    raise ValueError('统一模式填一个值；循环模式每行一个值')
                zone, value = raw, pool[i % len(pool)]
            else:
                raise ValueError('未知输入模式')
            for host in row_hosts.split(','):
                result.append(Record(zone, host, row_kind, value, priority, ttl))
                if len(result) > 10000:
                    raise ValueError('单次最多 10000 条记录')
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f'第 {i + 1} 行：{exc}') from None
    if not result:
        raise ValueError('请填写域名或批量记录')
    result = tuple(dict.fromkeys(result))
    grouped = {}
    for r in result:
        key = (r.zone, r.host)
        prior = grouped.setdefault(key, set())
        if prior and ('CNAME' in prior or r.kind == 'CNAME'):
            raise ValueError(f'{r.zone}/{r.host}：本次输入包含冲突的 CNAME 记录')
        prior.add(r.kind)
    return result
