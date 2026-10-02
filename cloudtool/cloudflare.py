from __future__ import annotations

import csv
import io
import ipaddress
import json
import re
from collections import defaultdict

from .models import Action, Plan, ApiError, canonical
from .execution import bounded_map
from .providers import register


from .permissions import PHASES

SETTINGS = {
    "SSL/TLS": {"ssl": ["strict", "full", "flexible", "off"],
                "always_use_https": ["on", "off"], "min_tls_version": ["1.2", "1.3", "1.1", "1.0"],
                "tls_1_3": ["on", "off", "zrt"], "automatic_https_rewrites": ["on", "off"],
                "opportunistic_encryption": ["on", "off"]},
    "缓存": {"cache_level": ["aggressive", "basic", "simplified"],
           "browser_cache_ttl": [14400, 0, 3600, 86400],
           "always_online": ["on", "off"], "development_mode": ["off", "on"]},
    "传输优化": {"http2": ["on", "off"], "http3": ["on", "off"],
               "0rtt": ["off", "on"], "early_hints": ["on", "off"],
               "websockets": ["on", "off"], "polish": ["off", "lossless", "lossy"]},
    "其他设置": {"security_level": ["medium", "high", "low", "essentially_off", "under_attack"],
               "browser_check": ["on", "off"], "email_obfuscation": ["on", "off"],
               "hotlink_protection": ["off", "on"], "ipv6": ["on", "off"]},
}


def domain(text):
    text = text.strip().rstrip(".").lower()
    try:
        text = text.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError(f"无效域名：{text}")
    if len(text) > 253 or "." not in text or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in text.split(".")):
        raise ValueError(f"无效域名（不要包含协议、路径或端口）：{text}")
    return text


def domains(text):
    return list(dict.fromkeys(domain(x) for x in text.splitlines() if x.strip()))


def dns_name(name, zone):
    name = name.strip().lower().rstrip(".")
    if not name or name == "@":
        return zone
    if name == zone or name.endswith("." + zone):
        result = name
    else:
        result = name + "." + zone
    try:
        result = result.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("无效的记录名")
    if len(result) > 253 or any(not re.fullmatch(r"(?:\*|[a-z0-9_-]{1,63})", x) for x in result.split(".")):
        raise ValueError(f"无效的记录名：{result}")
    return result


def dns_payload(raw, zone):
    item = {k: v for k, v in raw.items() if k in {"type", "name", "content", "ttl", "proxied", "priority", "data", "comment", "tags", "settings"}}
    item["name"] = dns_name(str(raw.get("name", "@")), zone)
    item["type"] = str(raw.get("type", "A")).upper()
    if item["type"] not in {"A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA", "HTTPS", "SVCB", "PTR", "URI", "NAPTR", "DS", "SSHFP", "TLSA", "CERT", "DNSKEY", "SMIMEA", "OPENPGPKEY", "LOC"}:
        raise ValueError("不支持的 DNS 类型")
    item["ttl"] = int(item.get("ttl", 1))
    if item["ttl"] != 1 and not 30 <= item["ttl"] <= 86400:
        raise ValueError("TTL 须为 1（自动）或 30–86400；最低值受套餐限制")
    proxy = item.get("proxied", False)
    if isinstance(proxy, str):
        if proxy.lower() not in {"true", "false", "1", "0"}:
            raise ValueError("proxied 须为 true/false")
        proxy = proxy.lower() in {"true", "1"}
    if not isinstance(proxy, bool):
        raise ValueError("proxied 须为布尔值")
    if proxy and item["type"] not in {"A", "AAAA", "CNAME"}:
        raise ValueError("只有 A/AAAA/CNAME 可以开启代理")
    if item["type"] in {"A", "AAAA", "CNAME"}:
        item["proxied"] = proxy
    else:
        item.pop("proxied", None)
    if item["type"] in {"A", "AAAA"}:
        address = ipaddress.ip_address(item.get("content", ""))
        if address.version != (4 if item["type"] == "A" else 6):
            raise ValueError("IP 地址与记录类型不匹配")
    if not item.get("content") and not item.get("data"):
        raise ValueError("DNS 内容或 data 不可为空")
    if item["type"] == "MX":
        item["priority"] = int(item.get("priority", 10))
        if not 0 <= item["priority"] <= 65535:
            raise ValueError("MX 优先级须为 0–65535")
    else:
        item.pop("priority", None)
    return item


def parse_records(text):
    if not text.strip():
        return []
    if text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        data = [data] if isinstance(data, dict) else data
    else:
        data = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    if not isinstance(data, list) or not data or any(not isinstance(x, dict) for x in data):
        raise ValueError("记录须为 JSON 对象数组或含表头的 CSV")
    return data


class Cloudflare:
    def __init__(self, client, store):
        self.client, self.store = client, store

    def zones(self):
        zones = self.client.all("/zones")
        self.store.cache("zones", zones)
        return zones

    def resolve(self, names):
        result = []
        for name in names:
            matches = self.client.all("/zones", {"name": name})
            matches = [x for x in matches if x["name"].lower() == name]
            if len(matches) != 1:
                raise ValueError(f"{name}：当前 Token 下找到 {len(matches)} 个匹配域名，请检查权限或 Account")
            result.append(matches[0])
        return result

    def inspect(self, zones, kind, options, workers=4):
        def one(z):
            base = f"/zones/{z['id']}"
            if kind == "DNS":
                result = self.client.all(base + "/dns_records", per_page=100)
            elif kind == "自定义主机名":
                result = self.client.all(base + "/custom_hostnames")
            elif kind == "页面规则":
                result = self.client.get(base + "/pagerules")
            elif kind == "规则集":
                result = self.client.get(base + "/rulesets/phases/" + options["phase"] + "/entrypoint")
            else:
                result = self.client.get(base + "/settings/" + options["setting"])
            return {"zone": z["name"], "result": result}
        return list(bounded_map(one, zones, workers, self.client.cancel))

    def plan(self, zones, operation, options, workers=4):
        if operation == "zone_add":
            account = options["account"].strip()
            if not re.fullmatch(r"[a-fA-F0-9]{32}", account):
                raise ValueError("添加域名必须填写目标 Cloudflare Account ID（32 位十六进制）")
            actions = [Action(name, "POST", "/zones", {"name": name, "account": {"id": account}, "type": "full"}, summary="添加域名") for name in options["names"]]
            return Plan(self.client.key, actions)
        if not zones:
            raise ValueError("请选择域名或输入完整域名")
        allowed = {z["name"] for z in zones}
        records = parse_records(options.get("records", "")) if operation in {"dns_add", "dns_upsert"} else []
        for record in records:
            if record.get("zone") and domain(record["zone"]) not in allowed:
                raise ValueError(f"导入记录的 zone 不在当前选定范围：{record['zone']}")
        options = {**options, "parsed_records": records}
        if operation == "rules_copy":
            source = domain(options["source"])
            source_z = self.resolve([source])[0]
            if source in allowed:
                raise ValueError("目标中包含源域名，请移除源域名")
            base = f"/zones/{source_z['id']}"
            if options["kind"] == "页面规则":
                options["source_rules"] = self.client.get(base + "/pagerules")
            else:
                options["source_rules"] = self.client.get(base + "/rulesets/phases/" + options["phase"] + "/entrypoint").get("rules", [])

        def one(z):
            return self._zone_plan(z, operation, options)
        actions = []
        for part in bounded_map(one, zones, workers, self.client.cancel):
            actions.extend(part)
        actions.sort(key=lambda a: a.target)
        if len(actions) > 100000:
            raise ValueError("单次操作超过 100000 条，请分批")
        return Plan(self.client.key, actions)

    def _zone_plan(self, z, op, opts):
        base, name = f"/zones/{z['id']}", z["name"]
        actions = []

        def add(method, path, body=None, before=None, guard="", summary=""):
            actions.append(Action(name, method, path, body, before, guard, summary))

        if op == "zone_delete":
            before = self.client.get(base)
            add("DELETE", base, before=before, guard=base, summary="删除整个域名及配置")
        elif op.startswith("dns_"):
            path = base + "/dns_records"
            current = self.client.all(path, per_page=100)
            if op in {"dns_add", "dns_upsert"}:
                raw = opts["parsed_records"] or [opts["record"]]
                raw = [r for r in raw if not r.get("zone") or domain(r["zone"]) == name]
                used = set()
                for r in raw:
                    body = dns_payload(r, name)
                    identity = (body["name"], body["type"], body.get("content", canonical(body.get("data"))))
                    upsert_id = identity[:2] if op == "dns_upsert" else identity
                    if upsert_id in used:
                        raise ValueError(f"{name}：导入包含重复记录或重复 upsert 目标")
                    used.add(upsert_id)
                    found = [x for x in current if x["name"] == body["name"] and x["type"] == body["type"]]
                    exact = [x for x in found if x.get("content") == body.get("content") and x.get("data") == body.get("data")]
                    if op == "dns_add":
                        if exact:
                            continue
                        add("POST", path, body, summary=f"添加 {body['type']} {body['name']}")
                    elif len(found) > 1:
                        raise ValueError(f"{name}：{body['name']} / {body['type']} 有多个记录，拒绝不明确的覆盖")
                    elif found:
                        old = found[0]
                        if all(old.get(k) == v for k, v in body.items()):
                            continue
                        endpoint = path + "/" + old["id"]
                        add("PATCH", endpoint, body, old, endpoint, f"更新 {body['name']}")
                    else:
                        add("POST", path, body, summary=f"添加 {body['name']}")
            else:
                filter_name = opts.get("filter_name", "").strip()
                filter_type = opts.get("filter_type", "全部")
                filter_content = opts.get("filter_content", "")
                for old in current:
                    if filter_name and old["name"] != dns_name(filter_name, name):
                        continue
                    if filter_type != "全部" and old["type"] != filter_type:
                        continue
                    if filter_content and old.get("content") != filter_content:
                        continue
                    endpoint = path + "/" + old["id"]
                    if op == "dns_delete":
                        add("DELETE", endpoint, before=old, guard=endpoint, summary=f"删除 {old['type']} {old['name']}")
                    elif op == "dns_proxy":
                        if old.get("proxiable") and old.get("proxied") != opts["proxied"]:
                            add("PATCH", endpoint, {"proxied": opts["proxied"]}, old, endpoint, f"代理 → {opts['proxied']}")
                    elif op == "dns_replace":
                        if not filter_content:
                            raise ValueError("解析替换需要填写精确的旧记录值，避免误改")
                        candidate = dns_payload({**old, "content": opts["new_content"]}, name)
                        if old.get("content") != candidate["content"]:
                            add("PATCH", endpoint, {"content": candidate["content"]}, old, endpoint, f"替换 {old['name']}")
        elif op == "settings":
            settings = opts["values"]
            if not isinstance(settings, dict) or not settings:
                raise ValueError("设置须为非空 JSON 对象")
            for setting, value in settings.items():
                if not re.fullmatch(r"[a-z0-9_]+", setting):
                    raise ValueError("无效 setting ID")
                if setting in {"minify", "brotli", "rocket_loader", "mirage"}:
                    raise ValueError(f"{setting} 已弃用，请查看官方弃用说明")
                path = base + "/settings/" + setting
                old = self.client.get(path)
                if old.get("editable") is False:
                    raise ValueError(f"{name}：{setting} 当前套餐不可编辑")
                if old.get("value") != value:
                    add("PATCH", path, {"value": value}, old, path, f"{setting} → {value}")
        elif op == "purge":
            body = opts["body"]
            if not isinstance(body, dict) or len(body) != 1 or not set(body) <= {"purge_everything", "files", "hosts", "tags", "prefixes"}:
                raise ValueError("清缓存须选择一种模式：purge_everything / files / hosts / tags / prefixes")
            if "purge_everything" in body and body["purge_everything"] is not True:
                raise ValueError("purge_everything 必须为 true")
            if "purge_everything" not in body:
                values = next(iter(body.values()))
                if not isinstance(values, list) or not values:
                    raise ValueError("清缓存目标须为非空数组")
                key = next(iter(body))
                for i in range(0, len(values), 100):
                    add("POST", base + "/purge_cache", {key: values[i:i+100]}, summary=f"清缓存 {key} {i+1}–{min(i+100,len(values))}")
            else:
                add("POST", base + "/purge_cache", body, summary="清除全部缓存")
        elif op.startswith("hostname_"):
            path = base + "/custom_hostnames"
            current = self.client.all(path)
            payloads = opts["payloads"]
            if not isinstance(payloads, list) or any(not isinstance(x, dict) for x in payloads):
                raise ValueError("自定义主机名须为 JSON 对象数组")
            seen = set()
            for raw in payloads:
                host = domain(raw.get("hostname", ""))
                if host in seen:
                    raise ValueError("自定义主机名列表包含重复项")
                seen.add(host)
                existing = [r for r in current if r["hostname"] == host]
                if op == "hostname_add":
                    if not existing:
                        add("POST", path, {**raw, "hostname": host}, summary=f"添加自定义主机名 {host}")
                else:
                    if len(existing) != 1:
                        raise ValueError(f"{host}：未找到唯一的自定义主机名")
                    endpoint = path + "/" + existing[0]["id"]
                    before = self.client.get(endpoint)
                    if op == "hostname_delete":
                        add("DELETE", endpoint, before=before, guard=endpoint, summary=f"删除自定义主机名 {host}")
                    else:
                        body = {k: v for k, v in raw.items() if k != "hostname"}
                        if not body:
                            raise ValueError("修改主机名需要 ssl / custom_origin_server 等字段")
                        add("PATCH", endpoint, body, before, endpoint, f"修改 {host}")
        elif op.startswith("rules_"):
            page = opts["kind"] == "页面规则"
            selected_ids = set(opts.get("ids", "").split())
            if page:
                path = base + "/pagerules"
                existing = self.client.get(path)
                if op == "rules_delete":
                    for old in existing:
                        if selected_ids and old["id"] not in selected_ids:
                            continue
                        endpoint = path + "/" + old["id"]
                        before = self.client.get(endpoint)
                        add("DELETE", endpoint, before=before, guard=endpoint, summary="删除页面规则 " + old["id"])
                else:
                    data = opts["source_rules"] if op == "rules_copy" else opts["rules"]
                    for raw in data:
                        body = {k: v for k, v in raw.items() if k in {"targets", "actions", "priority", "status"}}
                        if not body.get("targets") or not body.get("actions"):
                            raise ValueError("页面规则必须包含 targets 和 actions")
                        add("POST", path, body, summary="添加页面规则（复制保留原表达式）")
            else:
                phase = opts["phase"]
                if phase not in PHASES.values():
                    raise ValueError("未知规则阶段")
                entry = base + "/rulesets/phases/" + phase + "/entrypoint"
                try:
                    old = self.client.get(entry)
                except ApiError as exc:
                    if exc.status != 404:
                        raise
                    old = None
                existing = (old or {}).get("rules", [])
                # PATCH/PUT to one whole zone entrypoint; never remove managed/account rulesets.
                writable = {"id", "ref", "action", "action_parameters", "expression", "description", "enabled", "logging", "ratelimit", "exposed_credential_check"}
                retained = [{k: v for k, v in r.items() if k in writable} for r in existing]
                if op == "rules_delete":
                    rules = [r for r in retained if selected_ids and r["id"] not in selected_ids]
                    if len(rules) == len(retained):
                        return []
                else:
                    incoming = opts["source_rules"] if op == "rules_copy" else opts["rules"]
                    if not isinstance(incoming, list) or any(not isinstance(r, dict) for r in incoming):
                        raise ValueError("规则内容须为 JSON 对象数组")
                    incoming = [{k: v for k, v in r.items() if k in writable - {"id", "ref"}} for r in incoming]
                    if any(not r.get("expression") or not r.get("action") for r in incoming):
                        raise ValueError("每条规则须包含 expression 和 action")
                    rules = retained + incoming
                body = {"rules": rules}
                if old:
                    path = base + "/rulesets/" + old["id"]
                    add("PUT", path, body, old, entry, f"{phase}：{len(existing)} → {len(rules)} 条")
                elif rules:
                    body.update({"name": "CloudDesk " + phase, "kind": "zone", "phase": phase})
                    add("POST", base + "/rulesets", body, summary=f"创建规则集 {phase}")
        else:
            raise ValueError("未实现的操作")
        if op.startswith("dns_") and opts.get("dns_batch") and actions:
            batched = []
            for offset in range(0, len(actions), 100):
                chunk = actions[offset:offset + 100]
                body = {}
                snapshots = []
                for a in chunk:
                    key = {"DELETE": "deletes", "PATCH": "patches", "POST": "posts"}[a.method]
                    item = dict(a.body or {})
                    if a.method != "POST":
                        item["id"] = a.path.rsplit("/", 1)[1]
                    body.setdefault(key, []).append(item)
                    if a.before is not None:
                        snapshots.append(a.before)
                snapshots.sort(key=lambda r: r["id"])
                batched.append(Action(name, "POST", base + "/dns_records/batch", body,
                    snapshots if snapshots else None, base + "/dns_records" if snapshots else "",
                    f"DNS 批处理 · {len(chunk)} 条（{', '.join(body)}）", guard_kind="dns_batch"))
            return batched
        return actions


register("cloudflare", "Cloudflare", Cloudflare)
