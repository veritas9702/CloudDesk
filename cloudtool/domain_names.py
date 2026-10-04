"""Shared DNS domain normalization; no provider, UI or network dependencies."""
import re

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


