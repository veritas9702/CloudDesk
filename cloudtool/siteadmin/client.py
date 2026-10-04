import os
import time
"""SSM API adapter, matched to server/internal/api and resp contracts."""
import threading
import httpx
from .models import Credentials
from ..api_client import RateLimiter
from ..models import ApiError, fingerprint
from .diagnostics import network_reason, http_help


class SiteClient:
    title = '站点后台'
    def __init__(self, credentials, transport=None):
        credentials = Credentials.decode(credentials.encode())
        self.credentials = credentials
        self.key = fingerprint(credentials.encode())
        self.cancel = threading.Event(); self.limiter = RateLimiter(2)
        self._token = ''; self._refresh = ''; self.progress = None
        self.http = httpx.Client(base_url=credentials.url, timeout=httpx.Timeout(30, connect=10),
                                 follow_redirects=False, transport=transport,
                                 limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))

    def safe(self, value):
        text = str(value)
        for secret in (self.credentials.password, self._token, self._refresh, self.credentials.encode()):
            if secret: text = text.replace(secret, '[已隐藏]')
        return text[:2000]

    def _request(self, method, path, body=None, params=None, login=False, files=None, timeout=30):
        if self.progress: self.progress('@request', '等待', f'{method} {path} · 等待请求配额')
        self.limiter.acquire(self.cancel)
        if self.progress: self.progress('@request', '请求中', f'{method} {path} · 等待后台响应（超时 {timeout} 秒）')
        writing = method != 'GET' and not login
        try:
            response = self.http.request(method, path, json=body, params=params, files=files, timeout=httpx.Timeout(timeout,connect=10),
                headers={'Authorization': 'Bearer ' + self._token} if self._token and not login else {})
        except httpx.TransportError as exc:
            raise ApiError(f'{method} {path} · {type(exc).__name__}：{network_reason(exc)}', uncertain=writing) from None
        if 300 <= response.status_code < 400:
            raise ApiError('后台返回重定向，请直接填写最终后台地址；未转发凭据')
        try:
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get('code'), int): raise ValueError()
        except ValueError:
            raise ApiError(f'{method} {path} · HTTP {response.status_code}，响应不是 SSM JSON。{http_help(response.status_code)}',response.status_code,uncertain=writing) from None
        if response.status_code != 200 or result['code'] != 0:
            if response.status_code == 401 and not login: self.cancel.set()
            message = self.safe(result.get('message', '接口请求失败'))
            raise ApiError(f'{method} {path} · HTTP {response.status_code}：{message}。{http_help(response.status_code)}', response.status_code,
                           uncertain=writing and response.status_code >= 500)
        return result.get('data')

    def login(self):
        self._token = self._refresh = ''
        data = self._request('POST', '/api/auth/login', dict(username=self.credentials.username, password=self.credentials.password), login=True, timeout=15)
        if not isinstance(data, dict): raise ApiError('登录响应格式异常')
        token, refresh = data.get('access_token'), data.get('refresh_token', '')
        if not isinstance(token, str) or not token or not isinstance(refresh, str):
            raise ApiError('登录未返回有效访问令牌')
        self._token, self._refresh = token, refresh
        if data.get('must_change_password'):
            raise ApiError('后台要求修改初始密码，请先在浏览器完成后更新本机配置')
        if not isinstance(self._token, str) or not self._token: raise ApiError('登录未返回有效访问令牌')
        if data.get('user', {}).get('role') != 'admin':
            raise ApiError('批量创建站点需要此后台的管理员账户')

    def sites(self, keyword=''):
        rows, seen = [], set()
        for page in range(1, 10001):
            if self.progress: self.progress('@request', '读取站点', f'正在读取第 {page} 页，已读取 {len(rows)} 个站点')
            data = self._request('GET', '/api/sites', params=dict(page=page, size=200, keyword=keyword), timeout=15)
            if not isinstance(data, dict) or not isinstance(data.get('list'), list) or not isinstance(data.get('total'), int):
                raise ApiError('站点列表格式异常，未使用不完整数据')
            for row in data['list']:
                if not isinstance(row, dict) or not row.get('id') or 'code' not in row or 'primary_domain' not in row:
                    raise ApiError('站点字段缺失')
                if row['id'] in seen: raise ApiError('站点分页重复，请重新读取')
                seen.add(row['id'])
                # API includes unrelated push credentials; never cache or export those.
                rows.append({key: row.get(key, '') for key in ('id','code','name','primary_domain','link_protocol','page_count')})
            if len(rows) >= data['total']: return rows
            if not data['list']: raise ApiError('站点分页提前结束')
        raise ApiError('站点分页超过上限')

    def request(self, method, path, body=None):
        if method != 'POST' or path != '/api/sites': raise ValueError('此模块只支持创建站点')
        result = self._request(method, path, body)
        if not isinstance(result, dict) or not result.get('id'):
            raise ApiError('创建响应缺少站点 ID，请先核实远端', uncertain=True)
        return {'result': {key: result.get(key, '') for key in ('id','code','name','primary_domain')}}

    def publication(self, site_id):
        data=self._request('GET','/api/publish/versions',params={'site_id':site_id},timeout=15)
        if not isinstance(data,dict) or 'current' not in data or 'list' not in data:
            raise ValueError('发布记录响应不完整')
        current,history=data['current'],data['list']
        if current is not None:
            if not isinstance(current,dict) or current.get('site_id')!=site_id or current.get('is_current') is not True or type(current.get('version')) is not int or current['version']<=0:
                raise ValueError('当前发布版本无法核实')
            return '已发布'
        if history is None or history==[]:return '未发布'
        raise ValueError('存在发布历史但没有当前版本，请核对后台')

    def delete_site(self,site_id,code):
        if type(site_id) is not int or site_id<=0 or not code:raise ValueError('删除站点参数无效')
        return self._request('DELETE',f'/api/sites/{site_id}',{'confirm_code':code})

    def close(self):
        self._token = self._refresh = ''
        self.http.close()

    def template_step(self, site_id, stage, archive=None, progress=None):
        if not isinstance(site_id,int) or site_id <= 0: raise ValueError('无效站点 ID')
        if stage not in ('upload-template','sync','scan'): raise ValueError('无效模板操作')
        path=f'/api/sites/{site_id}/{stage}'
        if stage=='upload-template':
            with open(archive,'rb') as source:
                result=self._request('POST',path,files={'file':('template.zip',CancellableFile(source,self.cancel,progress),'application/zip')},timeout=300)
        else:
            result=self._request('POST',path,body={'force':False} if stage=='scan' else {},timeout=300)
        if not isinstance(result,dict): raise ApiError('流程响应格式异常，请核实后台',uncertain=True)
        return result


class CancellableFile:
    def __init__(self, source, cancel, progress=None):
        self.source,self.cancel,self.progress=source,cancel,progress
        self.total=os.fstat(source.fileno()).st_size
        self.last_report=0.;self.started=False
    def read(self,size=-1):
        if self.cancel.is_set(): raise ApiError('上传已中止，远端结果待核实',uncertain=True)
        if self.progress and not self.started:
            self.progress(0,self.total);self.started=True
        data=self.source.read(size)
        now=time.monotonic()
        if self.progress and (not data or now-self.last_report>=.15):
            # EOF is requested only after the previous multipart chunk was consumed.
            sent=self.source.tell() if not data else min(self.source.tell(),max(0,self.total-1))
            self.progress(sent,self.total);self.last_report=now
        return data
    def __getattr__(self,name): return getattr(self.source,name)
