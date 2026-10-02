"""Beginner instructions verified against Cloudflare documentation, 2026-10-02."""
from html import escape
from .permissions import FEATURES, RULE_PERMISSIONS, manual_permission_rows

TOKEN_URL = "https://dash.cloudflare.com/profile/api-tokens"
DOC_URL = "https://developers.cloudflare.com/fundamentals/api/get-started/create-token/"
PERMISSIONS_URL = "https://developers.cloudflare.com/fundamentals/api/reference/permissions/"

PERMISSIONS = [(f.title, "账户 Account" if f.id == "accounts" else "区域 Zone", f.permission.split(" → ")[0], {"read": "读取 Read", "edit": "编辑 Edit", "purge": "清除 Purge"}[f.access]) for f in FEATURES] + list(manual_permission_rows())

PAGE_PERMISSIONS = {
    0: "Zone → Zone → Read",
    1: "Zone → Zone → Edit；新建域名需要覆盖目标账户内所有 Zone 的资源范围",
    2: "Zone → DNS → Edit + Zone → Zone → Read",
    3: "Zone → DNS → Edit + Zone → Zone → Read",
    4: "Zone → DNS → Edit + Zone → Zone → Read",
    5: "Zone → Zone → Edit",
    6: "Zone → DNS → Edit + Zone → Zone → Read",
    7: "Zone → Zone Settings → Edit + Zone → Zone → Read",
    8: "Zone → SSL and Certificates → Edit + Zone → Zone → Read",
    9: "配置：Zone Settings → Edit；清缓存：Cache Purge；另需 Zone → Read",
    10: "Zone → Zone Settings → Edit + Zone → Zone → Read",
    11: "Zone → Zone → Read，并按所选规则类型添加编辑权限（见指南）",
    12: "Zone → Zone Settings → Edit + Zone → Zone → Read",
}


def guide_html():
    rows = "".join("<tr>" + "".join(f'<td width="{width}%">{escape(c).replace(" / ", " /<br>")}</td>' for c, width in zip(row, (29, 14, 38, 19))) + "</tr>" for row in PERMISSIONS)
    return f"""<style>
    body {{color:#26364b; font-size:13px; line-height:1.6;}}
    h2 {{color:#162d48;font-size:19px;margin-top:20px;}}
    p,li {{line-height:1.6;}} th {{background:#eaf0f7;text-align:left;}}
    td,th {{padding:9px;border-bottom:1px solid #e2e8f0;}}
    </style>
    <h2>1　自动填写基础与高级权限</h2><p>主界面点击“自动配置 Token”，选择平时的 Chrome / Edge。首次点击“准备助手并打开安装页”，开启开发者模式、点击 Load unpacked，粘贴已复制的目录并选择。此操作只需首次进行，准备文件不代表已完成安装。</p><p>确认已启用助手后，点击“打开网页并填写权限”。等待网页显示权限已填写并校验，核对资源范围，输入 IP 白名单并确认创建。复制新 Token 返回主界面“添加 Token”加密保存。助手不处理登录或验证码，不读取生成的 Token。真实 Cloudflare 页面尚待验收；若未出现成功提示，请勿用不完整权限直接创建。</p><h2>也可手工创建</h2>
    <p>登录 Cloudflare → 右上角个人资料 → API 令牌（API Tokens）→ 创建令牌 → 创建自定义令牌。<br>
    <a href="{TOKEN_URL}">打开 Cloudflare 的 API 令牌页面</a></p>
    <h2>2　只管理 DNS？先添加这两行</h2>
    <p><b>第一行：区域（Zone） → Zone → 读取（Read）</b><br>
    <b>第二行：区域（Zone） → DNS → 编辑（Edit）</b><br>
    用“添加更多”增加第二行。创建页默认的“账户”下拉框，要先改为“区域”。不同界面可能译为“区域 / 域 / Zone”。</p>
    <p>这样可以读取域名并管理 DNS、替换解析、开关代理。若用“Edit Zone DNS”模板，也要核对并补上 Zone → Read。</p>
    <h2>3　按功能增加权限</h2>
    <p>不必把下面全部勾上，只添加要用的功能。Edit 包含读取与修改，已选 Zone → Edit 时无需再选 Zone → Read。
    文档中的 Write 对应控制台的 Edit；名称可能同时显示新版和旧版英文。</p>
    <table width="100%" cellspacing="0"><tr><th>功能</th><th>第一个下拉框</th><th>第二个下拉框</th><th>第三个下拉框</th></tr>{rows}</table>
    <h2>4　资源范围怎么选</h2>
    <p><b>只管理已有域名：</b>区域资源 → 包括 → 特定区域 → 选中要管理的域名。批量管理多个域名可逐个增加，
    或选择需要的账户下所有区域。没有纳入资源范围的域名，本工具无法读取或操作。</p>
    <p><b>需要新建域名：</b>必须允许目标账户内的新 Zone，不能只限制到某个已存在域名；使用覆盖目标账户所有 Zone 的范围。
    程序中还要填写该账户的 Account ID，不能填写 Zone ID。</p>
    <p><b>账户资源：</b>添加 Account Settings → Read 时，选择目标账户；这项仅用于“读取可见 Accounts”，
    不需要它时可手工填写 Account ID。账户资源选择“所有账户”不能替代区域权限与区域资源范围。</p>
    <h2>5　IP 限制与有效期</h2>
    <p>客户端 IP 筛选可留空；需要限制时填写本机访问互联网的<b>公网出口 IP</b>，不要填写 192.168.x.x 等内网地址。
    有代理时出口可能是代理 IP。有效期按自己的需要设置；未到开始时间或已过期的令牌无法使用。</p>
    <h2>6　保存到 CloudDesk</h2>
    <p>继续查看摘要 → 创建令牌 → 复制一次性显示的 Token → 返回本工具点击“添加 Token”。
    令牌名称只是本地备注；<b>本地加密主密码由你自行设置，不是 Cloudflare 登录密码，也不是 Token。</b>
    保存后点击“读取域名”，选中域名 → 填参数 → 生成预览 → 确认执行。</p>
    <h2>常见问题</h2>
    <p><b>403 / 权限不足：</b>检查对应功能的编辑权限、区域资源范围，以及 IP 和有效期限制。<br>
    <b>域名为空：</b>先检查 Zone → Read，以及是否选中了正确账户和域名。<br>
    <b>读取成功但修改失败：</b>能读域名不代表有 DNS / 设置 / 规则编辑权限；也可能受套餐限制。<br>
    <b>主机名或规则不可用：</b>Cloudflare for SaaS、不同规则阶段可能受套餐与功能开通状态影响。<br>
    本工具不会尝试写入测试来验证权限，生成预览成功也不等于全部写权限已验证。</p>
    <p>核对日期：2026-10-02 · <a href="{DOC_URL}">官方创建步骤</a> · <a href="{PERMISSIONS_URL}">官方权限清单</a></p>"""
