# 职责划分

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

保持当前单层 Python 包，按文件职责组织；没有为整理目录新增框架或更改已有 Cloudflare 功能行为。
