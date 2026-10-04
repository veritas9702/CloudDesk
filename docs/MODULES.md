# 模块接入与职责

`shell.py` 仅负责平台切换和模块生命周期；`providers.py` 是模块注册目录。内置 Cloudflare 保留原来的窗口和业务入口，作为子工作空间嵌入。GNAME 独立在 `gname/`：

- `models.py`：不可变记录、域名验证、四种批量输入解析。
- `client.py`：认证签名、HTTP、分页、错误与重试。
- `controller.py`：读取、冲突策略、计划和执行用例；不访问 Qt。
- `ui.py`：输入收集、调用控制器、渲染结果；不实现接口签名或业务删除策略。

共用 `Vault`、`Store`、`Action/Plan`、`bounded_map/execute`、`RateLimiter`、`Worker`、`TableModel`、表单/表格/五行输入组件和公网 IP 控件。GNAME 没有复制 Cloudflare 的执行器。共用执行器新增可选的远端校验回调，原 Cloudflare 调用方式不变。

## 热插拔

热插拔仅面向开发接入，主界面只显示平台切换按钮，不提供模块安装、移除或关闭按钮。

开发时使用 `providers.load_plugin(folder)` 注册可信本地模块，随后调用宿主 `refresh_modules()` / `open_module(key)`。卸载工作空间调用 `unload_module(key)`；注销外部模块调用 `remove_plugin(key)`。忙碌模块返回 False，不中断任务。外部模块仅在当前会话注册，重启不会自动执行外部目录。

开发者负责确认模块来源；加载过程会执行其 Python 代码。普通用户无需理解或操作这套机制。

模块目录提供 `module.json`：

```json
{"id":"my_provider","title":"我的平台","api_version":1,"entry":"entry.py"}
```

`entry.py` 导出 `create_workspace(root)`，返回 QWidget 或 QMainWindow。`root` 已限定在本机 `CloudDesk/modules/<id>`，模块内部应继续按账户隔离。入口以 Python 包加载，同目录文件使用相对导入。模块代码需要可信，不面向普通用户开放加载入口。

工作空间契约：

1. `busy` 准确表示所有未结束后台作业。宿主拒绝卸载忙碌模块。
2. `closeEvent` 在安全停止时释放线程、定时器、HTTP 客户端和数据库；未能停止时拒绝关闭。
3. 切换可见性不改变作业。不得调用 QApplication.quit、修改全局样式或使用其他模块的凭据。
4. 新依赖需随未来发布包提供；宿主不会自动运行安装命令。Python 导入兼容的模块可以免重启加入，替换正在运行模块的代码不属于热插拔范围。

内置平台的工厂通过注册表添加，新增平台无需向 Cloudflare 控制器增加分支。
