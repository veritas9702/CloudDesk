# 职责划分

- `crawler/`：独立网站采集模块，模型 / SQLite 队列 / 文档解析 / 异步引擎 / 控制器 / UI 分层，复用公共 Worker 和界面控件。见 [采集模块](CRAWLER.md)。

- `shell.py`：平台切换栏、模块工厂加载与安全卸载（开发接口）；各工作空间独立存活，切换标签不取消任务。
- `gname/models.py` / `client.py` / `controller.py` / `ui.py`：GNAME 输入模型、签名接口、业务控制器与视图，复用现有执行/审计/加密/Qt 组件。见 [模块接入](MODULES.md)。

- `models.py`：操作、计划、异常与规范化数据。
- `credentials.py` / `storage.py`：加密凭据、按 Token 隔离的缓存与审计。
- `api_client.py`：HTTP、分页、限速、重试和脱敏。
- `cloudflare.py` / `operations.py` / `execution.py`：提供商适配、业务调度、有限并发执行。下层不依赖 Qt。
- `permissions.py`：权限和规则阶段的唯一目录；`token_templates.py` / `browser_token_model.py` 为纯模型；`tools/generate_extension.py` 生成扩展数据。
- `ui_components.py` / `qt_jobs.py` / `table_model.py`：共享控件、后台任务与表格模型。
- `public_ip.py` / `public_ip_ui.py`：匿名公网 IP 服务与后台检测控件，不接收 Token。
- `ui.py` / `browser_token_ui.py` / `token_view_ui.py`：窗口与用户交互。
- `browser_launcher.py` / `extension_setup.py`：普通浏览器启动和静态助手部署，不读取浏览器配置。
- 扩展 `form.js` 在 MAIN 环境填写、回读表单；`assistant.js` 管理任务提示；`bridge.js` 在 ISOLATED 环境传递固定模式；`popup.js` 管理弹窗。没有令牌提取或自动提交。

不同 Token 使用独立客户端、数据库和视图状态；后台作业使用输入快照。可共享限流预算，不共享业务数据。

本次移除已无界面入口的旧模板向导、管理令牌创建流程、`core.py` 兼容导出层和受控浏览器路径辅助函数。测试直接引用所属模块，避免无用中转。

Cloudflare 保持原来的实现和数据路径；新平台使用独立子包。通用执行器提供可选的远端校验回调，避免在控制器中重复并发与审计代码。

- `automation_model.py`：接入意图、输入校验和预览数据；`automation.py`：分步编排；`automation_ui.py`：表单与事件呈现。复用 Cloudflare 计划、GNAME 客户端、有限并发执行器和审计，不引入第二套 HTTP 或调度实现。注册商联动只使用临时独立客户端，既有 GNAME 工作区的生命周期和取消信号保持独立。

- `siteadmin/`：SSM 站点后台的模型 / API / 控制器 / 视图，开发工厂接入既有平台注册表。`workspace_jobs.py` 提供可复用的 Qt 作业生命周期；`domain_names.py` 统一三个模块的域名规范化，移除 GNAME 重复实现。

### Cloudflare manual-registrar onboarding

`cf_onboarding_ui.py` owns account selection, DNS review and NS export presentation. `cf_onboarding.py` owns persisted per-token onboarding results, account discovery, scan/review and ownership checks. Zone creation reuses `OnboardingController`, provider plans and audited execution; no registrar credentials are required. Scan reads never import records automatically. Accepted record bodies exclude server metadata, retain record data/priority and skip identical existing records. Token switches clear the view. All API work uses the host worker and shared rate limiter.
