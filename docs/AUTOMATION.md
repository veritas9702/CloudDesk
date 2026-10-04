# Cloudflare 自动化接入

入口：Cloudflare → 左侧「自动化接入」。这是手动确认后连续执行的批量流程，不是定时任务；执行期间请保持程序运行。

1. 在顶部选择 Cloudflare Token，填写目标 Account ID（可读取可见账户）。
2. 填写域名，每行一个。解析值支持统一、逐行配对（域名,值）、循环分配。DNS 可关闭；启用时按同名同类型添加或更新记录，多个同名同类型记录会拒绝模糊覆盖。
3. 选择主机记录、代理和站点设置。默认不修改 SSL / HTTPS 重写 / Always Online；主机记录支持逗号分隔，例如 `@,www`。
4. NS 可选手动修改，或选择已在 GNAME 模块保存的账户；添加 GNAME 账户后点击刷新账户列表。
5. 点击生成预览，再用「查看 / 导出明细」检查计划，确认执行。

执行顺序：创建或复用目标账户的 Full Zone → 配置 DNS → 应用站点设置 → 修改 NS。最后一步才切换注册商，可避免先切到尚未配置的 Zone。新 Zone 的具体请求在创建后按预览参数生成，并记录到审计。NS 提交成功不代表全球生效，Cloudflare 初始 pending 状态属正常情况。

新 Zone 不自动迁移原有全部解析；邮件等业务记录应另行补齐。切换 NS 前检查原注册商 DNSSEC / DS 配置。非 GNAME 注册商会显示「待手动」及目标 NS，可从明细导出。

Token 需 Zone Edit；DNS 配置需 DNS Edit；站点设置需 Zone Settings Edit。读取账户列表另需 Account Settings Read。资源范围须覆盖目标账户的新 Zone。GNAME API 使用账户自身的 APPID / APPKEY 和 IP 白名单。

单域名失败停止该域名的后续步骤，其他域名继续。不会自动回滚已成功步骤；写入结果未知时先核实远端，再重新预览。预览有效期 15 分钟，同一预览不可重复执行。重新预览会读取当前 Zone、DNS 和设置，不会盲目重放旧任务。

请求使用现有超时、限速和审计；并发域名可设置 1–8，请求上限独立于并发数。GNAME 另受其共享限速约束。切换平台不会中断任务，取消当前 Cloudflare 流程也不会取消 GNAME 工作区自己的任务。

模板、流程审计按 Cloudflare Token 隔离。配置模板不保存域名、解析值或注册商凭据。联动 GNAME 时创建独立请求客户端，使用选定的 GNAME 凭据；该流程的 NS 请求结果记录在发起流程的 Cloudflare 审计中，凭据不会写入流程明细。程序包不包含本机账户数据库。

本版不含 Telegram 通知或定时调度。

参考：[90 工具箱流程](https://www.90th.cn/automation/cloudflare)、[Cloudflare 创建 Zone API](https://developers.cloudflare.com/api/resources/zones/methods/create/)。
