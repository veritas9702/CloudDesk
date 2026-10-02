"""Single source for feature permissions and rule phases; no UI or network."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    key: str
    access: str
    permission: str

FEATURES = (
    Feature('zones', '读取域名 / 导出（必需）', 'zone', 'read', 'Zone → Read'),
    Feature('dns', 'DNS 增删改 / 替换 / 代理', 'dns', 'edit', 'DNS → Edit'),
    Feature('zone_write', '添加 / 删除域名', 'zone', 'edit', 'Zone → Edit'),
    Feature('settings', 'SSL/TLS / 缓存配置 / 优化 / 其他设置', 'zone_settings', 'edit', 'Zone Settings → Edit'),
    Feature('purge', '清除缓存', 'cache', 'purge', 'Cache Purge → Purge'),
    Feature('ssl', 'SSL 自定义主机名', 'ssl_and_certificates', 'edit', 'SSL and Certificates → Edit'),
    Feature('pages', '页面规则', 'page_rules', 'edit', 'Page Rules → Edit'),
    Feature('accounts', '读取账户列表（可选）', 'account_settings', 'read', 'Account Settings → Read'),
)
PRESETS = {'DNS 基础': ('zones', 'dns'), '常用管理': tuple(f.id for f in FEATURES if f.id != 'accounts'), '只读域名': ('zones',)}

@dataclass(frozen=True)
class RuleCapability:
    title: str
    phase: str
    permission: str

# These API permission names are known; their template URL keys are not documented.
RULES = (
    RuleCapability('WAF 自定义规则', 'http_request_firewall_custom', 'Zone WAF'),
    RuleCapability('缓存规则', 'http_request_cache_settings', 'Cache Rules / Cache Settings'),
    RuleCapability('重写 URL', 'http_request_transform', 'Transform Rules / Zone Transform Rules'),
    RuleCapability('请求头转换', 'http_request_late_transform', 'Transform Rules / Zone Transform Rules'),
    RuleCapability('响应头转换', 'http_response_headers_transform', 'Transform Rules / Zone Transform Rules'),
    RuleCapability('重定向规则', 'http_request_dynamic_redirect', 'Single Redirect / Dynamic URL Redirects'),
    RuleCapability('源站规则', 'http_request_origin', 'Origin Rules / Origin'),
    RuleCapability('配置规则', 'http_config_settings', 'Config Rules / Config Settings'),
    RuleCapability('压缩规则', 'http_response_compression', 'Response Compression'),
)
PHASES = {rule.title: rule.phase for rule in RULES}
RULE_PERMISSIONS = {rule.title: rule.permission for rule in RULES}

def preset_for(features):
    selected = set(features)
    return next((name for name, items in PRESETS.items() if selected == set(items)), '自定义')

def manual_permission_rows():
    """Group phases sharing one permission so guidance and wizard stay consistent."""
    groups = {}
    for rule in RULES:
        groups.setdefault(rule.permission, []).append(rule.title)
    return tuple((' / '.join(titles), '区域 Zone', permission, '编辑 Edit')
                 for permission, titles in groups.items())

def manual_checklist():
    return '\n'.join(f'{title}：Zone → {permission} → Edit'
                     for title, scope, permission, access in manual_permission_rows())

