# CloudDesk

Windows 本地 Cloudflare 批量管理工具。客户端 v0.10.4，浏览器权限助手 v0.1.5。

## 使用

双击 **start.bat**。它只启动 `app/CloudDesk/CloudDesk.exe`；没有打包程序时才使用本项目 `.venv` 运行源码。

首次点击“自动配置 Token”，按窗口提示在 Chrome / Edge 加载本地助手。选择基础或完整权限，等待网页校验成功后核对资源范围和 IP 白名单，再确认创建。第二步提供“获取公网 IP / 复制 IP”。生成的 Token 返回工具加密保存。

助手 0.1.5 的真实网页填写已由用户截图确认。更换网络时重新检查公网出口。Token、任务数据和已安装助手位于 `%LOCALAPPDATA%/CloudDesk`，不随程序目录复制。

## 目录

| 目录 / 文件 | 用途 |
| --- | --- |
| `app/` | 唯一的当前 Windows 程序 |
| `cloudtool/` | Python 应用、业务逻辑与共享组件 |
| `browser_extension/` | 普通浏览器的权限填写助手 |
| `docs/` | 使用、架构与验证说明 |
| `tests/` | 当前功能的单元与集成测试 |
| `tools/` | 权限目录生成、发布与清理脚本 |
| `examples/` | 批量导入示例 |
| `THIRD_PARTY_LICENSES/` | 第三方授权文件 |
| `.venv/` | 本机开发环境；发布包不包含 |

## 开发

`setup.bat` 创建运行环境。需要浏览器回归测试时执行 `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`。

`build.bat` 使用 `requirements-build.txt` 构建到 `app/`；中间文件位于 `.build/`。以后不再建立按版本命名的程序目录。构建前退出 CloudDesk。

测试：`.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`。

发布：`.venv\Scripts\python.exe tools/package_release.py 输出目录`，只打包当前文件，不携带开发环境、历史构建或本机凭据。

旧版清理：双击 **cleanup.bat**。脚本检查当前程序与项目路径，要求先退出 CloudDesk，只清理已列出的旧构建及缓存。保留开发环境和本机业务数据。

- [功能与使用](docs/USAGE.md)
- [架构职责](docs/ARCHITECTURE.md)
- [验证记录](docs/VALIDATION.md)
