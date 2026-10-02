"""Cloudflare template domain model. No Qt, I/O, credentials or browser state."""
from dataclasses import dataclass
import json
from urllib.parse import urlencode

TEMPLATE_DOC = 'https://developers.cloudflare.com/fundamentals/api/how-to/account-owned-token-template/'

from .permissions import Feature, FEATURES, PRESETS

@dataclass(frozen=True)
class TokenTemplate:
    name: str
    features: tuple[str, ...]

    def permissions(self):
        unknown = set(self.features) - {f.id for f in FEATURES}
        if unknown:
            raise ValueError('存在不支持的权限选项')
        selected = set(self.features) | {'zones'}
        return tuple(f for f in FEATURES if f.id in selected and not (f.id == 'zones' and 'zone_write' in selected))

    def url(self):
        name = self.name.strip()
        if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise ValueError('请输入 1–100 个字符的令牌名称，不能包含换行或控制字符')
        permissions = [{'key': f.key, 'type': f.access} for f in self.permissions()]
        return 'https://dash.cloudflare.com/profile/api-tokens?' + urlencode({
            'permissionGroupKeys': json.dumps(permissions, separators=(',', ':')),
            'accountId': '*', 'zoneId': 'all', 'name': name,
        })
