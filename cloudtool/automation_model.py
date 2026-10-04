"""Cloudflare onboarding intent and immutable preview data; no UI or HTTP."""
import csv
import re
import time
import uuid
from dataclasses import dataclass, field
from .cloudflare import domain, dns_payload


@dataclass(frozen=True)
class Site:
    name: str
    value: str = ''


@dataclass(frozen=True)
class WorkflowOptions:
    account: str
    sites: tuple[Site, ...]
    hosts: tuple[str, ...] = ('@', 'www')
    record_type: str = 'A'
    dns_enabled: bool = True
    proxied: bool = False
    ssl: str = ''
    rewrites: str = ''
    always_online: str = ''
    registrar: str = ''

    def settings(self):
        return {k: v for k, v in {'ssl': self.ssl, 'automatic_https_rewrites': self.rewrites,
                                  'always_online': self.always_online}.items() if v}

    def records(self, site):
        return [dns_payload(dict(name=h, type=self.record_type, content=site.value,
                                 proxied=self.proxied, ttl=1), site.name) for h in self.hosts]

    def validate(self):
        if not re.fullmatch('[a-fA-F0-9]{32}', self.account):
            raise ValueError('请填写目标 Cloudflare Account ID（32 位十六进制）')
        if not self.sites or len(self.sites) > 1000 or len({s.name for s in self.sites}) != len(self.sites):
            raise ValueError('每次填写 1–1000 个不同的域名')
        if self.ssl not in ('', 'strict', 'full', 'flexible', 'off') or any(
            v not in ('', 'on', 'off') for v in (self.rewrites, self.always_online)
        ):
            raise ValueError('无效的站点设置')
        if self.record_type not in ('A', 'AAAA', 'CNAME', 'TXT'):
            raise ValueError('自动化支持 A / AAAA / CNAME / TXT')
        if self.dns_enabled and not self.hosts:
            raise ValueError('请填写至少一个主机记录')
        for site in self.sites:
            if domain(site.name) != site.name: raise ValueError('域名格式未规范化')
            if self.dns_enabled: self.records(site)
        return self


def parse_sites(text, mode, value, dns_enabled=True):
    if len(text) + len(value) > 1024 * 1024:
        raise ValueError('输入过大，请分批')
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    values = [x.strip() for x in value.splitlines() if x.strip()]
    sites = []
    for i, raw in enumerate(lines):
        try:
            if mode == '逐行配对' and dns_enabled:
                row = next(csv.reader([raw]))
                if len(row) != 2: raise ValueError('格式应为：域名,解析值')
                name, content = row
            else:
                name = raw
                if dns_enabled and (not values or (mode == '统一解析值' and len(values) != 1)):
                    raise ValueError('统一模式填一个解析值；循环模式每行一个解析值')
                content = values[i % len(values)] if values and dns_enabled else ''
            sites.append(Site(domain(name), content.strip()))
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f'第 {i + 1} 行：{exc}') from None
    return tuple(sites)


@dataclass
class WorkflowPreview:
    owner: str
    options: WorkflowOptions
    steps: list
    zones: dict
    plans: dict
    registrar_ns: dict
    created: float = field(default_factory=time.time)
    batch: str = field(default_factory=lambda: uuid.uuid4().hex)
