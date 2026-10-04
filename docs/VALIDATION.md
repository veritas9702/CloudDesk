# 当前验证范围

## 已验证

- 用户截图确认助手 0.1.5 在真实 Cloudflare 页面填写并核对 13 项权限，摘要包含高级规则和 IP 筛选。
- 核心单元测试覆盖凭据隔离、业务计划、请求重试、取消、防重放、权限数据和静态助手部署。
- 浏览器离线回归覆盖搜索输入、中文别名、输入值与选中值区分、部分状态重试、导航参数清除及 MAIN/ISOLATED 通信。
- GUI 回归覆盖 Token 明文查看、批量域名输入、页面切换和公网 IP 后台检测。

## 0.11.0 多平台检查

- 61 项单元测试通过；新增 GNAME 签名、四种输入、分页、写入不重试、冲突保护、防重放、隔离和层依赖检查。
- 双平台真实执行器 + 模拟 HTTP 并行测试通过：Cloudflare 180 请求全部完成；取消 GNAME 后只发出 4 请求，Cloudflare 取消信号未改变，各自数据库不串记录。
- 双平台执行期间切换 139 次，测试环境事件循环最大间隔 46 ms；运行中拒绝卸载，空闲重开、第三方本地模块加载与移除通过。
- Cloudflare 36 项页面尺寸检查通过；320 个模拟执行请求期间事件循环最大间隔 19.24 ms；40000 条合并状态事件压力检查最大间隔 23.65 ms。
- Token 查看/复制/关闭/隔离/加密检查和公网 IP 检测/取消检查通过。
- 0.11.0 Windows 打包程序自检通过：Cloudflare / GNAME 两个工作空间均加载、Cloudflare 12 个表单完整、本机加密检查通过、退出码 0。

上述时延是本机模拟接口结果，不是所有电脑或公网接口的性能承诺。旧版本清理由限定路径的脚本单独执行，不通过启动应用触发。

## 边界

权限填写成功不代表套餐支持所有高级功能。没有做真实账户批量写入或吞吐压力测试。网络检测测试使用模拟服务；运行时公网 IP 取决于本机网络出口。

## 0.11.1 界面调整

顶部改为 62 像素单行平台切换栏，去掉用户端加载/移除/打开模块按钮和平台关闭叉号，开发层保留注册与生命周期接口。Cloudflare 嵌入模式去掉重复品牌标题。

61 项单元测试通过；双平台并发与取消隔离测试通过，切换 203 次、事件循环最大间隔 32 ms。已检查 Cloudflare 与 GNAME 的实际渲染截图，顶栏文字不换行。

## 0.11.2 布局与数值控件

GNAME 改为左右操作范围/记录设置，执行参数放入独立操作栏，结果区按需展开。两个平台复用带单位、无原生箭头的数值控件。1160×850 与 1440×960 渲染检查通过，域名框至少五行。Cloudflare 36 项布局检查和并发执行回归通过，双平台取消隔离检查通过。

## 0.12.0 自动化接入

69 项单元测试通过，覆盖只读预览、顺序执行、单域名失败隔离、未知写入、NS 漂移保护、手动 NS、已有 Zone 复用、过期 / 防重放 / 账户隔离与取消。自动化 GUI 的五行布局、后台预览 / 执行、模板和切换 Token 清空状态通过。原 Cloudflare 36 项页面尺寸检查、320 个模拟请求、40000 条合并事件回归通过。双平台并发 / 取消隔离通过（179 次切换，事件循环最大间隔 47 ms）。新流程未对真实账户执行写入，真实权限和网络仍需实际使用验证。

## 0.13.0 站点后台工作流

78 项单元测试通过。SSM 模拟接口覆盖真实源码约定的登录响应、管理员与初始密码限制、只读预览、创建与重复跳过、预览后冲突、超时不重试、响应脱敏、账户边界和拒绝重定向。GUI 离线检查涵盖 1160×850 / 1440×960、五行输入、平台切换时工作继续、忙碌禁止卸载、空闲重开和第二账户清空数据。CF / GNAME 原并发回归通过：189 次切换、事件循环最大间隔 47 ms。GUI 测试临时替代 DPAPI（测试进程无法调用），生产 Vault 未改动。未在真实后台建站，未修改 ssm-main。

## 0.14.0 模板上传工作流

86 项单元测试通过。新增测试覆盖五步请求顺序、ZIP 根路径、模板不足、相同内容副本、源文件改动、占用冲突、上传结果未知停止后续步骤、已有内容保护、成功上传后取消续跑不重传。GUI 模拟流程完整验证预览与执行。用户提供的两个采集目录仅只读校验，未上传到真实后台；ssm-main 未修改。


## 0.14.1 工作流恢复
89 项单元测试及站点 GUI 冒烟通过。新增上传重试、核实完成后跳过上传、站点 ID 变化和过期状态检查。网络错误提供分类和解决建议；恢复不释放原模板绑定。未测试真实后台上传，未修改 ssm-main。


## 0.14.2 站点列表与模板分配
91 项单元测试通过；GUI 冒烟覆盖列表/记录自动加载、五行域名输入、模板目录可见、任务详情。已有空站点手动分配复用模板工作流，校验站点 ID、原配置、模板唯一绑定；数据库重开后保留五步骤结果。未操作真实后台，未修改 ssm-main。


## 0.14.3 手动分配反馈
增加实际按钮路径 GUI 回归：选择占用模板弹出占用站点和处理建议，保持站点列表，远端无写入；选择可用模板成功后跳转预览，确认执行后完成上传/同步/扫描，复用已有站点。


## 0.14.4 上传进度
上传文件流按字节报告百分比及大小，限频 150ms，通过原有合并事件刷新界面。100% 表示本机文件流传输结束，仍需等待后台确认解压。并发测试校验每个上传操作的独立进度、起止字节、成功顺序。

多站点流程保留有界并发，上传及等待解压响应独占一个通道；等待上传可取消，未获得通道不写 uploading 状态。并发回归证明两站点上传峰值为 1。client_max_body_size 为单请求大小限制，队列不绕过 413。


## 0.14.5 列表直接恢复
站点列表对绑定中的任务提供继续 / 恢复按钮，未绑定空站点才允许分配模板。显示具体阶段，恢复成功自动跳转预览；失败弹出原因。恢复原配置直接按目标查询持久化记录，不受显示历史 5000 条限制。GUI 回归覆盖上传失败→列表恢复→确认执行→上传/同步/扫描成功，未重复创建站点。


## 0.15.0 模板管理
99 项单元测试及 GUI 流程回归通过。模板管理查询当前账户完整站点列表；明确点击后再次核实 ID/编码均不存在才原子归档并释放。保留释放历史和原任务审计；预览及执行前检查原站点重新出现。已有站点、网络失败、绑定变化、其他账户均不释放。GUI 回归覆盖拒绝释放现存站点→删除模拟站点→成功释放并刷新历史。未修改 ssm-main，未操作真实后台。


## 0.16.0 网站采集

- 110 项单元测试通过，其中采集专项 11 项：静态资源图、本地链接、暂停与重启、仅重试失败项、损坏文件恢复、体积与页数限制、查询参数、中文响应编码、SVG 大小写、图片去重、并发上限、无扩展名资源与现有模板打包兼容。
- `tests/crawler_smoke.py` 使用真实本机 HTTP 服务器验证 GUI 下载；切换 Cloudflare、GNAME、站点后台不中断采集；任务重载保留状态，忙碌时拒绝卸载。
- 1160×820 与 1440×960 离屏截图检查：域名输入、保存目录、启动按钮首屏可见。
- 没有向用户后台创建站点或上传模板，没有修改 ssm-main。
- 尚未验证任意互联网动态网站的视觉一致性。此版仅静态采集，不承诺运行时 JS/API 的离线还原。


## 0.16.7 动态追加与干净发布

- 132 项全量测试通过，随后新增独立本机数据根隔离测试通过。GUI 本机 HTTP 验证运行中输入和追加、任务自动执行、成功移除输入、重复已保存网址清除、四模块切换。
- 模拟不同电脑的 LOCALAPPDATA：新根目录无旧任务和保存路径，默认使用新桌面 WebsiteTemplates。未声称使用另一台实体电脑测试。
- 修正清理脚本的过时程序路径，保留当前版本和运行中的发布目录；发布包额外排除 SQLite WAL/SHM 和模板缓存目录。

## 0.16.6 去重与界面响应

- 132 项单元测试通过。已完成任务重复导入不新建记录；缺失文件复用原任务补下载，已有完整文件不重复下载。
- 本机 HTTP GUI 冒烟通过，增加慢准备阶段的 Qt 心跳验证及重复开始跳过结果检查。
- 200 域名真实本地队列准备（不发网络请求）耗时 1.94 秒，点击开始返回低于 0.1 毫秒；20 毫秒定时器最大观测间隔 32 毫秒。此为当前测试机样本，不代表任意硬件、完整网络采集过程都无延迟。

## 0.16.5 关键样式验收与缓存清理

- 全量 130 项测试通过，随后新增英文默认目录迁移测试，统计与目录 4 项测试通过。覆盖 CSS 403、无后缀样式失败、旧版误发布结果隔离、失败缓存清理后重采、禁止清理正常模板、旧中文路径不移动文件。
- GUI 本机 HTTP 冒烟及 1160×820 布局检查通过。没有声称解决目标网站自身的 403，也没有删除用户实际模板或断点。

## 0.16.4 原站路径与编码

- 128 项单元测试通过；补测子目录 GBK 首页、GBK CSS、HTML 元素与脚本保留、查询参数、CDN 隔离、Windows 非法名称、大小写及文件目录冲突、旧任务哈希兼容。子目录续采额外验证不重下、不改回旧路径。
- GUI 本机 HTTP 冒烟通过。打包 PYZ 检查确认包含修复后的断点路径逻辑。
- 原站结构指目录层级、静态名称、页面元素及编码的保留；本地链接改写、静态后缀和安全文件名映射属于必要差异，不声称字节级复制或动态后端功能复制。

## 0.16.3 轻量模式与小模板

- 124 项单元测试通过，覆盖小残缺结果输出、失败项重试、轻量模式的 HTML/CSS/JS 保存、图片字体不下载且绝对链接保留、续采不改变原模式，以及发现队列批量提交和失败回滚。
- 本机隔离 SQLite 入队基准：1000 个 URL 逐项提交 4.101 秒，按文档批量提交 0.054 秒。仅反映入队阶段，不能外推为网络下载倍速。新增队列排序和内容查重索引；并发上限保持不变。
- 本机 HTTP GUI 冒烟与 1160×820 / 1440×960 布局检查通过。
- 对比用户 kdlgroupltd.com 两份实际目录：小飞兔 13 文件共 291,071 字节，无图片；CloudDesk 175 文件共 21,501,977 字节，其中 JPG/PNG 161 个共 21,211,305 字节。小飞兔图片引用原站；CloudDesk 文件无 SHA-256 内容重复。未声称已验证任意站点的视觉一致性。

## 0.16.2 采集统计与默认目录

- 122 项单元测试通过，覆盖独立计时、暂停后续计、速度衰减、旧数据兼容、目录创建及选择持久化。
- 本机 HTTP GUI 冒烟通过：采集结束后显示统计、重载保持记录与目录，四模块并存运行；1160×820 和 1440×960 布局截图检查通过。
- 不改写旧任务未知的历史耗时；不提供尚未发现完整资源集合时的虚假剩余倒计时。

## 0.16.1 采集恢复与验收

- 119 项单元测试通过。新增首页 403 零成果失败、1–3 层语义、取消旧体积和单文件限制、小残缺缓存隔离、大残缺可检查、旧任务迁移不丢数据、HTTP 200 错误页、JS 空壳、等待心跳、快速暂停、缺失文本源恢复和兼容请求头回归。
- 本机 HTTP GUI 冒烟及 1160×820 / 1440×960 布局验证通过，四模块切换及重载保持独立。
- 实际验证 share.america.gov：首页、中文首页、用户指定文章，旧自定义 UA 为 403，浏览器兼容 UA 为 200；保留 CloudDeskCapture 标识的兼容 UA 也为 200。
- 对根首页做 1 层真实采集，保存 1 页面、114 文件、约 6.12 MB。18 个资源失败（17 个 404、1 个 403）如实标记部分完成；抽查源 CSS 和源资源 URL 确认存在源站无效引用，未把失败资源伪报为完整。
- 未修改 ssm-main；采集测试不涉及用户后台写入。用户本机历史数据库的工具读取受权限限制，未声称已检查或改动其实际记录；迁移逻辑使用隔离样本验证。


## 0.16.8
- 29 crawler/portability tests passed: pending draft survives reopen, explicit clearing persists, first upgrade restores unpublished tasks, new local data root stays empty.
- GUI smoke passed: completed seeds removed, saved captures skipped, live append, and pending input restored after module close/reopen.


## 0.16.9
- 31 crawler/portability tests passed, including restored queue waiting events and confirmed redirect aliases.
- GUI smoke passed, including live append, saved-input exclusion, reopen persistence and compact layout.
- Synthetic 50-site check: 17 saved leaves 33 pending; bulk resume queues exactly the 33 unpublished tasks.


## 0.16.10
- 34 tests passed: state/time ordering, stale-snapshot protection, confirmed deletion, skip-and-remove failed inputs, queue deletion, and file-level resume.
- Crawler GUI smoke passed at compact and large sizes.
- Missing source cache no longer forces a verified local HTML file to be downloaded again; corrupt files still retry individually.


## 0.16.11
- 36 regression tests and GUI smoke passed.
- Added running-deletion test passed: task directories removed and the other site continues to completion.
- Verified local-cache preview while another task is running, confirmation cancellation, and isolation of sibling directories during removal.
- Styled context menu rendered and visually inspected.


## 0.16.12
- Crawler regressions plus targeted UI tests verified size threshold boundaries, visible-only checks, cancel/confirm batch deletion, and retained domain preview after adding columns.
- Size aggregation test verifies unique saved paths and excludes failed-file sizes.
- Final GUI smoke passed; compact and completed layouts inspected.

### 0.16.13 Cloudflare onboarding

- Full unittest discovery: 152 tests passed; subsequent targeted suite: 16 passed including identical-DNS deduplication.
- New offline UI smoke validates account auto-selection, zone preview/create/reuse, NS clipboard export, activation refresh, batch handoff and token reset at 1160×850 and 1440×1000.
- Service tests cover scan failure preserving NS, account permission fallback, read-only review, selected DNS import, stale scan/foreign-account rejection and creation failure exclusions.
- Source self-check passes. No live domains or registrar settings were modified; API behavior was validated against Cloudflare documentation and fake clients.

### 0.16.14 saved Token connection recovery

Tests start the real Cloudflare window with an encrypted vault and exercise cancelled startup unlock, wrong password followed by retry, preserved form input, atomic connection failure cleanup, and account reads recovering a saved but locked Token. HTTP requests use MockTransport and no real credentials.

Validation result: 158 unit tests passed; onboarding UI smoke and encrypted-token view smoke passed. No live API calls were used.

### 0.16.15 batch usability and failed capture cleanup

163 unit tests passed before the crawler addition; four crawler interaction tests passed afterward, including failed-only filtering, confirmation cancellation, removal of associated temporary directories and preserving partial/completed/running tasks. All 11 Cloudflare operation forms fit at 1440×960 and 1160×850 without form scrolling in their default state. Mock HTTP task smoke exercised visible intermediate states, empty DNS explanations, event-loop responsiveness and six successful guarded SSL writes. No live accounts were modified.

0.16.16：离线 GUI 回归覆盖慢请求禁用重复加载、读取超时后恢复按钮及重试、先创建空站点再补配模板（保留原站点 ID，创建请求不增加），并覆盖单站分配流程。

首页失败自动清理：45 项采集回归通过，另 5 项界面交互回归通过（含自动移除列表及输入网址）；HTTP 403/拦截页面清理、动态空壳与资源缺失保留、暂停续采保持原行为。

0.16.17：168 项单元回归通过；新测试覆盖打包失败后后续域名执行、上传结果未知后的独立调度、注入失败恢复不重传、批量预览跳过待核实域名。离线 GUI 验证结果按域名汇总、恢复/另选模板按钮分支；未对真实后台写入。

0.16.18：173 项回归通过；站点 GUI 测试通过；新增按需模板指纹、逐域名预览事件、完成站点不扫描库、二进制伪 HTML 上传拦截、GIF 资源修正后缀和引用测试。对本机 brometal 模板只读预检，准确拒绝 code~q-d9fc91d45c09.html（实际 image/gif），未修改模板或远端站点。

0.16.19：189 项单元测试通过。新增 16 项六步流程测试覆盖：TDK 分配先于修改、独立唯一值与重试复用、严格六步顺序、失败域名隔离、已有模板和完成步骤跳过、新模板扫描后加工、提交结果未知禁止重放及任务 ID 绑定、查询超时与取消后恢复、转换只重试失败文件（包括重试请求被拒后仍保留范围）、不完整明细阻止重放、待复核不能假成功、251 页批量统计检测、两个站点独立异步进展、账户隔离和站点变更保护。

新增 tests/site_pipeline_smoke.py 通过：真实 Qt 页面勾选、逐站 TDK 预览、确认执行、完成后不重复提交、已有站点加工入口；1160×850 和 1440×960 截图检查通过，无配置区上下滚动与控件遮挡。原站点后台 GUI 回归也通过。全部 HTTP 使用 MockTransport；接口契约对照本地 SSM 源码，未向真实后台提交加工任务。

0.16.20：205 项单元测试全部通过。新增未发布状态严格核实、完整域名复制、保留导入站点配置，以及失败站点一次重建流程测试；覆盖预检/模板占用失败不删除、已发布站点保护、删除结果未知不重放、第二次失败停止、TDK 保留及旧模板隔离。

站点列表与自动重建 Qt 离线 GUI 测试通过；1160×850、1440×960 布局检查通过。冻结程序自检退出 0（ok=true、frozen=true），两个新增模块确认打入包。全部测试使用模拟后台，未删除或修改真实站点。

0.16.21：207 项单元测试通过。新增真实加密凭据重开窗口、空账户回退域名归属、重复读取域名自动显示、空结果终态、401 失败后恢复读取测试。复现旧版账户请求已结束仍显示“正在读取”；修复终态反馈，并避免网络/鉴权错误被账户回退吞掉。cf_onboarding_smoke 与 cf_task_smoke 通过，覆盖接入、进度、界面响应和 SSL 批处理。全部使用模拟接口，未使用真实 Token 或操作远端账户。
0.16.21 冻结程序自检通过：退出码 0，ok=true、frozen=true、12 个表单。

0.16.22：211 项单元测试通过。新增模板大小策略测试覆盖下载超限清理且其他站点继续、严格大于边界、已有目录清理和配置持久化、异常目录身份保护、续采超限在网络请求前删除。旧采集交互与删除回归通过。

crawler_smoke 使用本地 HTTP 服务通过完整采集、增量队列、续采、模块切换、重开页面的自动检查及关闭流程；1160×820、1440×960 截图检查采集布局，无按钮拥挤或控件遮挡。此次测试只删除临时测试模板，未运行用户真实模板清理。
0.16.22 冻结程序自检退出 0、ok=true，体积策略模块确认已打入包。

0.16.23：完整单元回归 215 项通过；随后增加模板目录在扫描中消失的隔离测试，模板/指纹相关 27 项回归全部通过（当前共 216 项测试）。新增预览缓存测试验证未变化模板不重读内容、文件增加/删除/修改使缓存失效、上传打包仍检查真实内容、二进制伪 HTML 不写入缓存、同目录逐文件扫描响应取消。

site_preview_smoke 通过：扫描进度更新、取消后明确未生成计划、重试与缓存命中后确认按钮恢复，预览无后台写入。site_pipeline_smoke 与 site_rebuild_smoke 通过：六步、已完成跳过、既有站点入口、首次失败一次重建及完成。缓存仅加速预览，不能跳过执行前的完整打包校验；首次读取新模板依然受磁盘速度影响。
0.16.23 冻结程序自检退出 0、ok=true；打包前已再次核对构建输入为最新源码。

## 0.16.24 接入 SSL、加工后发布和域名访问

- 完整单元回归 224 项通过；之后补充域名链接规范化和非法输入两项，所在模块 8 项回归通过（合计 226 项不同测试）。
- Cloudflare 接入覆盖自动切换 custom + flexible、复用已符合配置跳过写入、权限/设置失败显示与跨域名隔离；CF 接入 GUI 和批量 SSL 六个审计写入回归通过。
- 发布覆盖六步依赖、旧断点仅补发布、摘要传递、无有效预检拒绝提交、原任务超时恢复、丢失提交响应后任务 ID 核对、失败不重复发布及不自动删站。
- GUI 覆盖真实鼠标点击 www 链接（模拟默认浏览器打开）、配置协议、非链接列仅选择、运行中模块切换、失败重建一次、取消后重新预览、未发布自动填充、复制域名、1160/1440 宽度布局。运行中模拟任务事件循环最大间隔 46 ms；这是本机离线测量，不是公网或所有机器的时延承诺。
- 只修改客户端；后台源码只读用于接口核对。未在真实 Cloudflare 账户写入，未在真实站点发布。
- 0.16.24 Windows 冻结程序自检通过：退出码 0，ok/frozen 为 true，12 个 Cloudflare 表单、Cloudflare/GNAME 工作空间、本机加密与字体检查正常。
