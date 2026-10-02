"""Browser form requirements, shared with the API permission catalogue."""
from dataclasses import dataclass
from .permissions import RULE_PERMISSIONS
from .token_templates import TokenTemplate

# Dashboard translations are presentation aliases, not API permission IDs/keys.
TRANSLATIONS = {
    'Zone': ('区域', '区域 Zone'), 'DNS': ('DNS',),
    'Zone Settings': ('区域设置',), 'Cache Purge': ('清除缓存',),
    'SSL and Certificates': ('SSL 和证书', 'SSL及证书'),
    'Page Rules': ('页面规则',), 'Account Settings': ('帐户设置', '账户设置'),
    'Zone WAF': ('区域 WAF',), 'Cache Rules': ('缓存规则',),
    'Cache Settings': ('缓存设置',), 'Transform Rules': ('转换规则',),
    'Zone Transform Rules': ('区域转换规则',),
    'Single Redirect': ('单一重定向', '单个重定向'),
    'Dynamic URL Redirects': ('动态 URL 重定向',),
    'Origin Rules': ('源站规则',), 'Origin': ('源站',),
    'Config Rules': ('配置规则',), 'Config Settings': ('配置设置',),
    'Response Compression': ('响应压缩',),
}

def aliases(names):
    return tuple(dict.fromkeys(value for name in names for value in (name, *TRANSLATIONS.get(name, ()))))

@dataclass(frozen=True)
class BrowserPermission:
    scope: tuple[str, ...]
    names: tuple[str, ...]
    access: tuple[str, ...]
    title: str

@dataclass(frozen=True)
class BrowserTokenRequest:
    name: str
    features: tuple[str, ...]
    rules: tuple[str, ...]
    browser: str = 'auto'

    def permissions(self):
        if self.browser not in ('auto', 'chrome', 'msedge'):
            raise ValueError('请选择 Chrome 或 Edge')
        template = TokenTemplate(self.name, self.features)
        template.url()
        rows = []
        zone, account = ('Zone', '区域'), ('Account', '账户', '帐户')
        access = {'read': ('Read', '读取'), 'edit': ('Edit', '编辑'), 'purge': ('Purge', '清除')}
        for feature in template.permissions():
            name = feature.permission.split(' → ')[0]
            rows.append(BrowserPermission(account if feature.id == 'accounts' else zone,
                         aliases((name,)), access[feature.access], feature.title))
        seen = set()
        for title in self.rules:
            if title not in RULE_PERMISSIONS:
                raise ValueError('不支持的高级规则类型')
            names = RULE_PERMISSIONS[title]
            if names in seen:
                continue
            seen.add(names)
            rows.append(BrowserPermission(zone, aliases(names.split(' / ')), access['edit'], title))
        return tuple(rows)

    def url(self):
        self.permissions()
        # Start from one documented permission, then fill every row through UI.
        return TokenTemplate(self.name, ('zones',)).url()
