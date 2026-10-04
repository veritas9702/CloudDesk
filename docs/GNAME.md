# GNAME 模块

CloudDesk 0.11.2 使用顶部单行平台切换栏。Cloudflare 和 GNAME 各自保存页面与后台任务，切换平台不会取消任务。账户、客户端、预览、审计和取消信号独立。用户界面不提供模块加载、移除和标签关闭入口。开发层仍支持空闲工作空间卸载，执行中禁止卸载。

## 首次使用

1. 点击顶部 GNAME → 添加账户。
2. 在 GNAME 用户中心 → 经销商 → API 设置申请 APPID / APPKEY。开启域名列表、解析列表、新增/删除解析接口权限；使用 NS 修改时另外开启域名修改 DNS。若平台要求 IP 白名单，使用添加账户窗口的公网 IP 检测并在官网配置。
3. 输入本机账户备注、APPID、APPKEY，读取域名。选中域名可以送入批量输入框或读取 DNS。
4. 填写参数 → 生成预览 → 检查每条添加/删除 → 确认执行。

凭据使用现有 Vault 的 Windows DPAPI，保存在 `%LOCALAPPDATA%/CloudDesk/gname`；审计按凭据指纹分库。不改动 Cloudflare 原有数据目录。复制程序到另一台电脑需要重新添加账户。

## 批量输入

- 统一记录值：每行一个域名，下面填一个记录值。
- 逐行完整记录：`example.com|www,@|A|192.0.2.1`，或 `example.com|@|MX|mx.example.com|5`。
- 域名与记录值配对：`example.com,192.0.2.1`。值含逗号时使用 CSV 双引号。
- 循环分配：域名每行一个，记录值每行一个；按输入顺序循环分配。

支持文本导入、多主机记录、A/CNAME/MX/URL/TXT、默认线路、MX 优先级。根据官方新增解析参数，普通 TTL 为 600 秒，MX 可设 1–600 秒。AAAA 等未在此接口文档列出的类型没有擅自开放。

勾选冲突替换时，仅处理默认线路上同名同类型以及 CNAME 冲突记录，明确列出删除请求。已经满足的记录跳过。执行每个域名前重新读取记录，远端发生变化则停止该域名后续操作；其他域名继续。删除后添加不是原子事务，添加失败时请查看审计。超时的写请求不自动重试，核实远端后重新预览。

另外支持按精确主机与类型批量删除、批量修改 NS、域名和 DNS 记录查询/CSV 导出、任务日志导出。批量任务使用有界调度，最多 8 个域名并发，默认 2；GNAME 进程请求预算最多 2 次/秒，仍可能受平台更严格限制。

本次范围是 GNAME 域名/DNS 管理。参考页中的宝塔网站绑定是另一平台功能，尚未接入。没有进行真实 GNAME 账户写入测试，也不声称模拟测试等同于生产验证。

## 官方接口依据

- [新增解析](https://www.gname.com/zhcn/domain/api/jiexi/add)
- [解析列表](https://www.gname.com/domain/api/jiexi/list)
- [删除解析](https://www.gname.com/domain/api/jiexi/del)
- [域名列表](https://www.gname.com/domain/api/domain/list)
- [修改 NS](https://www.gname.com/domain/api/domain/xgdns)
- [签名算法](https://www.gname.com/domain/api/rule/anquan?lang=zhcn)

请求使用文档 API 主机的 HTTPS 地址 `https://api.gname.net`，保留证书校验，禁止重定向。签名依据参数排序、PHP urlencode 兼容编码、追加 APPKEY、MD5 大写的算法实现。官方示例注释的 MD5 与展示的 stringB 不一致；单元测试使用独立 .NET MD5 验证后的结果。
