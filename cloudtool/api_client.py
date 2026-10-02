"""Cloudflare HTTP transport, pagination, retry and rate limits."""
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
from .models import ApiError, Cancelled, fingerprint, canonical

class RateLimiter:
    def __init__(self, rate=2.0):
        self.rate = rate
        self.lock = threading.Lock()
        self.next = 0.0

    def acquire(self, cancel):
        while True:
            if cancel.is_set():
                raise Cancelled("任务已取消")
            with self.lock:
                now = time.monotonic()
                delay = self.next - now
                if delay <= 0:
                    self.next = now + 1.0 / max(0.1, self.rate)
                    return
            if cancel.wait(min(delay, 0.2)):
                raise Cancelled("任务已取消")

    def defer(self, seconds):
        with self.lock:
            self.next = max(self.next, time.monotonic() + seconds)


# Only rate budget is shared. Credentials, connections, responses and storage are not.
PROCESS_LIMITER = RateLimiter(3.0)


class Client:
    BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, token, cancel=None, rate=2.0, transport=None, global_limiter=None):
        self.key = fingerprint(token)
        self._token = token
        self.cancel = cancel or threading.Event()
        self.limiter = RateLimiter(rate)
        self.global_limiter = global_limiter or PROCESS_LIMITER
        self.http = httpx.Client(base_url=self.BASE, headers={"Authorization": f"Bearer {token}"},
                                 timeout=httpx.Timeout(30, connect=10),
                                 limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
                                 follow_redirects=False, transport=transport)

    def safe(self, message):
        return str(message).replace(self._token, "[TOKEN]")[:4000]

    def request(self, method, path, body=None, params=None):
        if not path.startswith("/") or "://" in path or ".." in path or "?" in path or "#" in path:
            raise ValueError("不允许的 API 路径")
        for attempt in range(5):
            self.limiter.acquire(self.cancel)
            self.global_limiter.acquire(self.cancel)
            try:
                response = self.http.request(method, self.BASE + path, json=body, params=params)
            except httpx.TransportError as exc:
                if method != "GET":
                    raise ApiError("连接中断，写入结果未知；请读取远端核实后重新生成计划", uncertain=True) from exc
                if attempt == 4:
                    raise ApiError("读取连接失败或超时，请检查网络") from exc
                if self.cancel.wait(min(2 ** attempt, 15)):
                    raise Cancelled()
                continue
            if response.status_code == 429:
                value = response.headers.get("Retry-After", "")
                try:
                    delay = float(value)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        delay = 2 ** (attempt + 1)
                delay = max(1, delay)
                self.limiter.defer(delay)
                self.global_limiter.defer(delay)
                if attempt < 4:
                    continue
            if response.status_code >= 500:
                if method != "GET":
                    raise ApiError(f"HTTP {response.status_code}：写入结果未知；请先核实远端", response.status_code, True)
                if attempt < 4:
                    if self.cancel.wait(min(2 ** attempt, 15)):
                        raise Cancelled()
                    continue
            try:
                envelope = response.json()
            except ValueError:
                raise ApiError(f"HTTP {response.status_code}：非 JSON 响应", response.status_code, method != "GET")
            if not isinstance(envelope, dict):
                raise ApiError("API 响应格式无效", response.status_code, method != "GET")
            if response.is_error or envelope.get("success") is not True:
                errors = envelope.get("errors", [])
                raise ApiError(self.safe(f"HTTP {response.status_code}：{canonical(errors)}"), response.status_code)
            return envelope
        raise ApiError("重试次数耗尽")

    def get(self, path, params=None):
        return self.request("GET", path, params=params)["result"]

    def all(self, path, params=None, per_page=50):
        results = []
        for page in range(1, 100001):
            envelope = self.request("GET", path, params={**(params or {}), "page": page, "per_page": per_page})
            values = envelope.get("result")
            if not isinstance(values, list):
                raise ApiError("分页端点未返回列表")
            results.extend(values)
            info = envelope.get("result_info") or {}
            if info.get("total_pages") is not None:
                if page >= int(info["total_pages"]):
                    return results
            elif not values or len(values) < per_page:
                return results
        raise ApiError("分页超过安全上限；未使用不完整数据")

    def close(self):
        self.http.close()
