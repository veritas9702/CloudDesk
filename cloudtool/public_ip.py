"""Anonymous public-IP adapter. Never receives an API Token or a Vault."""
import ipaddress
import httpx
from .models import Cancelled

TRACE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'

def parse_public_ip(trace):
    values = [line[3:].strip() for line in trace.splitlines() if line.startswith('ip=')]
    if len(values) != 1:
        raise ValueError('检测服务没有返回唯一的公网 IP')
    address = ipaddress.ip_address(values[0])
    if not address.is_global:
        raise ValueError('检测结果不是公网 IP，请在 Cloudflare 页面手动核对')
    return str(address)

class PublicIpService:
    def __init__(self, transport=None):
        self.transport = transport

    def detect(self, cancel):
        if cancel.is_set():
            raise Cancelled()
        # Separate anonymous session: authenticated API headers must never leak here.
        with httpx.Client(timeout=httpx.Timeout(6, connect=3), follow_redirects=False,
                          transport=self.transport) as client:
            with client.stream('GET', TRACE_URL) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    if cancel.is_set():
                        raise Cancelled()
                    content.extend(chunk)
                    if len(content) > 16384:
                        raise ValueError('检测服务响应过大')
        if cancel.is_set():
            raise Cancelled()
        return parse_public_ip(content.decode('utf-8'))
