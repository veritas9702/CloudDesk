"""Actionable transport diagnostics, independent from presentation."""
import httpx


def network_reason(exc):
    if isinstance(exc,httpx.ConnectTimeout): return '连接后台超时。检查地址、端口、代理和后台 IP 白名单。'
    if isinstance(exc,httpx.ReadTimeout): return '等待后台响应超时。后台可能仍在解压或处理；先检查该站点目录及服务器日志，再选择继续或重试。'
    if isinstance(exc,httpx.WriteTimeout): return '发送文件超时。检查上行网络、代理上传限制及服务器接收超时。'
    if isinstance(exc,httpx.ConnectError): return '连接失败。检查后台是否在线、端口 / 防火墙，以及 HTTPS 证书配置。'
    if isinstance(exc,httpx.RemoteProtocolError): return '后台或反向代理中断连接。检查代理上传大小限制、请求超时及服务器磁盘空间。'
    return '网络传输中断。检查网络、代理和服务器日志；上传是否完成需在后台核实。'


def http_help(status):
    return {401:'登录已失效，请重新登录后重试。',403:'检查管理员权限、IP 白名单和后台授权。',
        413:'请求体过大：除程序 300 MB 限制外，还需检查 Nginx / 宝塔的上传大小限制。',
        429:'后台限流，请降低请求上限并稍后重试。',502:'网关未收到正常响应，检查后台进程和代理日志。',
        504:'网关等待后台超时，检查代理超时；后台任务可能仍在运行。'}.get(status,'核对后台返回信息及服务器日志。')
