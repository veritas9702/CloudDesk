# 功能与使用说明

## 功能范围

| 模块 | 已实现 |
| --- | --- |
| Token | 多配置管理、加密保存、同 Token 去重、切换清空业务视图 |
| Zone | 分页读取、批量添加、批量删除、状态筛选、CSV 导出 |
| DNS | 模板批量添加、唯一匹配更新、CSV/JSON 导入、读取/JSON 导出、精确值替换 |
| DNS 删除 | 名称/类型/内容筛选删除，或清空所选域名全部解析 |
| 代理 | 可代理记录的批量开启/关闭 |
| SSL/TLS | ssl、always_use_https、min_tls_version、tls_1_3、automatic_https_rewrites 等 |
| 自定义主机名 | SaaS 主机名批量添加/修改/删除、验证状态读取，使用 JSON 参数 |
| 缓存 | 全部/URL/主机名/标签/前缀清除，缓存级别、浏览器 TTL、开发模式等 |
| 传输优化 | HTTP/2、HTTP/3、0-RTT、Early Hints、WebSockets、Polish |
| 规则 | 页面规则及 9 个 Rulesets 阶段的读取、添加、同 Token 内复制、批量删除 |
| 其他设置 | 常用选项，以及现行单项 Zone Settings API 的 JSON 批量修改 |
| 任务 | 有界并发、取消、限流、预览、逐请求状态、修改前快照、审计导出 |

复杂 DNS（例如 SRV/CAA）、自定义主机名和规则使用 JSON 编辑器；这是高级参数界面，不是 Cloudflare 全部设置的表单复刻。规则模板默认禁用，需要自行改写条件和 enabled/status 后启用。WAF 托管规则部署、账户级规则集、Worker、R2 等不在本版范围。

## DNS 导入示例

CSV 必须使用 UTF-8（支持 BOM），有表头：

```csv
zone,name,type,content,ttl,proxied,priority
example.com,@,A,192.0.2.10,1,true,10
example.net,www,CNAME,target.example.net,1,false,10
```

JSON 示例：

```json
[
  {"zone":"example.com","name":"@","type":"A","content":"192.0.2.10","ttl":1,"proxied":true},
  {"zone":"example.net","name":"_service._tcp","type":"SRV","data":{"priority":10,"weight":5,"port":443,"target":"service.example.net"},"ttl":3600}
]
```

含 `zone` 的记录只应用于该域名，且域名必须在所选范围中；没有 `zone` 的记录会套用到每个所选域名。导入内容优先于单条模板。名称 `@` 表示根域名，`*` 表示实际通配符记录；筛选名称留空才表示全部。TTL 1 表示自动，其余最低 TTL 取决于套餐。

“添加”跳过相同名称/类型/内容的已有记录；不会顺便修改其 TTL 或代理状态。需要修改时用“添加或更新”。该模式要求名称+类型只匹配一条记录，多条 A/AAAA 等记录会报错，避免任意覆盖。

## 并发、性能与故障语义

- 网络在后台线程运行。默认 4 个并发域名，可配置 1–12；同一域名中的更改保持顺序。
- 默认每秒 2 次请求，可配置 0.2–3。程序还具有每秒 3 次的进程总限速。Cloudflare 全局限制可能按用户/账户累计，其他程序和控制台操作也占额度，增加 Token 并不等于增加额度。
- 默认开启 **DNS 原生批处理**：同一 Zone 的最多 100 条修改合成一个 `/dns_records/batch` 请求。可关闭以逐条执行。计划和日志按“请求/批”展示，完整记录位于详情 JSON。Cloudflare 单个 DNS 批请求具有数据库事务语义，但网络传播不是原子的，跨批次也不是一个事务。
- 205 条同域名代理修改的模拟测试合成 3 个写入请求，而不是 205 个；此为请求合并结果，不代表真实生产吞吐。
- 任务队列最多提前提交并发数的 2 倍，避免一次创建海量 Future；表格使用 Qt 数据模型，状态合并每 100 毫秒刷新。
- 遇到 429 遵循 Retry-After，并暂停调度速率；GET 的连接问题和 5xx 最多重试 5 次。写请求遇到超时、连接中断、5xx 等不确定结果不会重放，标记“结果未知”。
- 删除/修改前对预览快照做检查。DNS 批处理用一次分页列表复核该批涉及的记录。检查与写入之间仍存在竞态窗口，Cloudflare 接口不提供本工具可用的跨请求锁。
- 预览有效期 15 分钟；每份计划只在界面执行一次。新建记录预览后若远端被其他客户端修改，最终以 Cloudflare 校验结果为准。
- 某个域名中的请求失败后跳过该域名剩余请求，其他域名继续。取消会停止新请求并等待在途请求结束，不能撤销已经执行的操作。
- 异常退出后，执行中的请求标记为“结果未知”；尚未开始的请求标记为“未执行”。不自动恢复写入，避免重复创建或重复删除。
- 不承诺无限并发、跨批原子性、自动回滚或固定吞吐。实际速度取决于域名数量、记录数量、API 延迟、权限、套餐和限流。

## Token 隔离与本地文件

数据目录：`%LOCALAPPDATA%\CloudDesk`。

```text
profiles.json                    # 名称、Token 指纹、加密凭据
tokens/<sha256-token>/state.sqlite3 # 此 Token 专属缓存和审计
application.lock                 # 单实例锁
```

每个 Token 有独立 HTTP 客户端、凭据、SQLite 数据库、域名缓存及任务历史。计划同时绑定 Token 和存储身份，禁止跨 Token 执行。任务进行时不允许切换 Token；切换清空域名、计划、导入记录及业务字段。只有防止超限的进程请求预算共享，不共享业务数据。

主密码模式采用 PBKDF2-HMAC-SHA256（600,000 次、随机盐）和 AES-256-GCM（随机 nonce），Token 不以明文写盘。Windows DPAPI 模式使用用户范围加密，不回退到明文。本机测试环境的 DPAPI 调用返回 WinError 2，因此默认使用已验证的主密码模式。

审计快照和域名缓存是本地明文业务数据，不包含 Authorization 请求头。Token 运行时存在进程内存中；本地加密不防御已控制当前用户会话的恶意程序。移除配置只移除加密凭据，保留独立历史。相同真实 Cloudflare 资源若被两个 Token 授权访问，云端资源本身当然仍是同一个；本工具只隔离本地会话和数据，不复制云端资源。

## API 权限与套餐

按所需功能授予最小权限，并限制到目标账户/域名。常见权限包括 Zone Read/Edit、DNS Read/Edit、Zone Settings Read/Edit、Cache Purge、Page Rules Read/Edit、Zone WAF Read/Edit、SSL and Certificates、对应 Rulesets 功能权限。界面“读取可见 Accounts”还需要账户读取权限；没有该权限可以手工填写 Account ID。

不同 Rulesets 阶段、自定义主机名、Polish 等可能需要独立权限或套餐。403/不可编辑设置会呈现真实 API 错误，不冒充成功。不要求或接受 Global API Key。

## 与旧工具的差异

参考 90 工具箱的功能分类，独立实现本地界面和 API 调用，不调用其服务器。Cloudflare 已弃用 Auto Minify、旧 Brotli 开关等接口，程序明确拒绝这些旧设置；压缩配置使用规则集中的“压缩规则”（可用性由套餐决定）。Zone Settings 使用逐项接口，避免依赖已弃用的整批设置接口。

规则复制是追加，不覆盖原规则；原表达式、域名、列表 ID 等保持原样，不承诺跨账户引用可用。规则集更新必须发送保留后的规则列表，所以执行前会核对整个入口规则集快照。只管理 Zone 阶段入口规则，未实现账户级和托管规则部署。

## 开发与扩展

凭据、隔离存储、HTTP、限流和执行分别位于各自模块，见 ARCHITECTURE.md。

`cloudtool/cloudflare.py`：Cloudflare 参数校验、查询及计划生成。

`cloudtool/providers.py`：Provider 注册入口。

`cloudtool/ui.py`：PySide6 界面、后台任务桥接、交互。

添加其他平台时，需要实现对应 adapter、凭据方式和页面，复用任务模型及限流基础设施；当前没有假装可用的其他平台选项。注册入口为后续扩展准备，并非即插即用的通用插件系统。

测试：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
$env:PYTHONPATH = (Get-Location).Path
.venv\Scripts\python.exe tests/ui_smoke.py
```

打包：运行 `build.bat`。可执行文件使用 PyInstaller onedir，不需要 Python。首次构建需要联网安装构建依赖。

## 验证边界

已使用模拟 HTTP 响应测试核心流程，已离屏渲染并检查中文界面。没有用户的真实 Token，因此没有对真实 Cloudflare 账户执行读写，也没有真实账户吞吐测量。建议首次使用选取一个测试域名，小批量确认权限、套餐和实际返回值后再扩大规模。

## 参考资料

- 功能分类：https://www.90th.cn/CloudFlare
- API：https://developers.cloudflare.com/api/
- DNS 批处理：https://developers.cloudflare.com/dns/manage-dns-records/how-to/batch-record-changes/
- 限流：https://developers.cloudflare.com/fundamentals/api/reference/limits/
- API 弃用：https://developers.cloudflare.com/fundamentals/api/reference/deprecations/
- Zone 设置：https://developers.cloudflare.com/api/resources/zones/subresources/settings/methods/edit/
- 自定义主机名：https://developers.cloudflare.com/api/resources/custom_hostnames/methods/create/
- 缓存清理：https://developers.cloudflare.com/api/resources/cache/methods/purge/
- Rulesets：https://developers.cloudflare.com/ruleset-engine/rulesets-api/update/
- 页面规则：https://developers.cloudflare.com/api/resources/page_rules/methods/create/

第三方组件的授权文件随打包依赖附带。CloudDesk 与 Cloudflare 及 90 工具箱无隶属关系。
