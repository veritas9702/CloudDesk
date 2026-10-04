"""Official GNAME form signing, bounded pagination and conservative retries."""
import hashlib
import json
import threading
import time
from urllib.parse import quote_plus
import httpx
from ..api_client import RateLimiter
from ..models import ApiError, Cancelled, fingerprint

READ_PATHS = {'/api/domain/list', '/api/resolution/list'}
WRITE_PATHS = {'/api/resolution/add', '/api/resolution/delete', '/api/domain/dns'}
GNAME_LIMITER = RateLimiter(2)


def credential(appid, appkey):
    if not appid.strip() or not appkey.strip() or any(c.isspace() for c in appid + appkey):
        raise ValueError('请填写有效 APPID 和 APPKEY，不要包含空白')
    return json.dumps([appid.strip(), appkey.strip()], separators=(',', ':'))


def signed(params, appid, appkey, now=None):
    data = {k: str(v).strip() for k, v in params.items()}
    data.update(appid=appid, gntime=str(int(time.time() if now is None else now)))
    raw = '&'.join(k + '=' + quote_plus(v, safe='').replace('~', '%7E') for k, v in sorted(data.items()))
    data['gntoken'] = hashlib.md5((raw + appkey).encode('utf-8')).hexdigest().upper()
    return data


class GnameClient:
    BASE = 'https://api.gname.net'
    title = 'GNAME'

    def __init__(self, appid, appkey, rate=2, transport=None):
        self.key = fingerprint(credential(appid, appkey))
        self._appid, self._appkey = appid, appkey
        self.cancel = threading.Event()
        self.limiter = RateLimiter(rate)
        self.http = httpx.Client(base_url=self.BASE, timeout=httpx.Timeout(30, connect=10),
                                 follow_redirects=False, transport=transport,
                                 limits=httpx.Limits(max_connections=8, max_keepalive_connections=4))

    def safe(self, error):
        return str(error).replace(self._appkey, '[APPKEY]').replace(self._appid, '[APPID]')[:2000]

    def request(self, method, path, body=None):
        if method != 'POST' or path not in READ_PATHS | WRITE_PATHS:
            raise ValueError('不支持的 GNAME 请求')
        reading = path in READ_PATHS
        for attempt in range(3):
            self.limiter.acquire(self.cancel)
            GNAME_LIMITER.acquire(self.cancel)
            try:
                response = self.http.post(path, data=signed(body or {}, self._appid, self._appkey))
            except httpx.TransportError:
                if reading and attempt < 2:
                    if self.cancel.wait(2 ** attempt):
                        raise Cancelled()
                    continue
                raise ApiError('网络请求失败；' + ('请稍后重试' if reading else '写入结果未知，请先读取远端核实'), uncertain=not reading) from None
            if reading and (response.status_code == 429 or response.status_code >= 500) and attempt < 2:
                try:
                    delay = min(60, max(1, float(response.headers.get('Retry-After', 2 ** attempt))))
                except ValueError:
                    delay = 2 ** attempt
                GNAME_LIMITER.defer(delay)
                continue
            if response.status_code != 200:
                raise ApiError(f'GNAME HTTP {response.status_code}，请核实网络/API权限', response.status_code,
                               not reading and response.status_code >= 500)
            try:
                envelope = response.json()
                if not isinstance(envelope, dict) or 'code' not in envelope:
                    raise ValueError()
            except ValueError:
                raise ApiError('GNAME 响应格式异常；写操作请核实远端', uncertain=not reading) from None
            if str(envelope['code']) != '1':
                raise ApiError(self.safe(envelope.get('msg', 'GNAME 拒绝请求')))
            return {**envelope, 'result': envelope.get('data')}
        raise ApiError('GNAME 读取重试已耗尽')

    def all(self, path, params=None):
        result, seen = [], set()
        for page in range(1, 10001):
            reply = self.request('POST', path, {**(params or {}), 'page': page, 'limit': 100})
            rows = reply.get('data')
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ApiError('GNAME 列表格式异常')
            marker = json.dumps(rows, sort_keys=True)
            if rows and marker in seen:
                raise ApiError('GNAME 分页重复，未使用不完整数据')
            seen.add(marker)
            result.extend(rows)
            count = reply.get('count')
            if count is not None and len(result) >= int(count):
                return result
            if not rows:
                if count is not None and len(result) < int(count):
                    raise ApiError('GNAME 分页提前结束')
                return result
            if count is None and len(rows) < int(reply.get('pagesize', 100)):
                return result
        raise ApiError('GNAME 分页超出上限')

    def close(self):
        self.http.close()
