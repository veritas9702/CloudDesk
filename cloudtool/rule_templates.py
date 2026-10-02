"""Disabled example rule payloads, independent of presentation."""
def example_rules(kind, phase):
    if kind == "页面规则":
        rules = [{"targets": [{"target": "url", "constraint": {"operator": "matches", "value": "*example.com/*"}}], "actions": [{"id": "always_use_https"}], "status": "disabled"}]
    else:
        action, params = {
            "WAF 自定义规则": ("managed_challenge", None),
            "缓存规则": ("set_cache_settings", {"cache": True}),
            "重写 URL": ("rewrite", {"uri": {"path": {"value": "/new-path"}}}),
            "请求头转换": ("rewrite", {"headers": {"x-example": {"operation": "set", "value": "demo"}}}),
            "响应头转换": ("rewrite", {"headers": {"x-example": {"operation": "set", "value": "demo"}}}),
            "重定向规则": ("redirect", {"from_value": {"status_code": 301, "target_url": {"value": "https://example.com"}, "preserve_query_string": True}}),
            "源站规则": ("route", {"origin": {"port": 8080}}),
            "配置规则": ("set_config", {"ssl": "strict"}),
            "压缩规则": ("compress_response", {"algorithms": [{"name": "brotli"}, {"name": "gzip"}]})
        }[phase]
        rules = [{"action": action, "expression": '(http.host eq "example.com")', "description": "请替换示例条件", "enabled": False}]
        if params:
            rules[0]["action_parameters"] = params
    return rules

