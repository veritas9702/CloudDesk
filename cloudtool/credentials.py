"""Encrypted local credential persistence."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .models import fingerprint

def protect(data: bytes, decrypt=False) -> bytes:
    """Windows DPAPI, scoped to the current Windows user; never plaintext fallback."""
    if os.name != "nt":
        raise RuntimeError("持久化 Token 需要 Windows DPAPI")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dest = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(dest.data, dest.size)
    finally:
        kernel.LocalFree(dest.data)


class Vault:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "profiles.json"
        self.profiles = json.loads(self.path.read_text("utf-8")) if self.path.exists() else []

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.profiles, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, self.path)

    def add(self, label, token, password=None):
        token = token.strip()
        if not label.strip() or not token or any(c.isspace() for c in token):
            raise ValueError("请输入名称及有效的 API Token（不能包含空白）")
        key = fingerprint(token)
        if any(p["id"] == key for p in self.profiles):
            raise ValueError("此 Token 已存在，请直接选择对应配置")
        if password is not None:
            if len(password) < 10:
                raise ValueError("加密主密码至少需要 10 个字符")
            salt, nonce = os.urandom(16), os.urandom(12)
            derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000, 32)
            encrypted = AESGCM(derived).encrypt(nonce, token.encode(), key.encode())
            profile = {"id": key, "label": label.strip(), "encryption": "aes-gcm",
                       "secret": base64.b64encode(salt + nonce + encrypted).decode()}
        else:
            profile = {"id": key, "label": label.strip(), "encryption": "dpapi",
                       "secret": base64.b64encode(protect(token.encode())).decode()}
        self.profiles.append(profile)
        try:
            self.save()
        except Exception:
            self.profiles.pop()
            raise
        return profile

    def token(self, profile, password=None):
        raw = base64.b64decode(profile["secret"])
        if profile.get("encryption") == "aes-gcm":
            if password is None:
                raise ValueError("请输入此配置的加密主密码")
            derived = hashlib.pbkdf2_hmac("sha256", password.encode(), raw[:16], 600000, 32)
            try:
                token = AESGCM(derived).decrypt(raw[16:28], raw[28:], profile["id"].encode()).decode()
            except Exception:
                raise ValueError("主密码错误或凭据文件损坏") from None
        else:
            token = protect(raw, True).decode()
        if fingerprint(token) != profile["id"]:
            raise ValueError("Token 配置校验失败")
        return token

    def remove(self, key):
        self.profiles = [p for p in self.profiles if p["id"] != key]
        self.save()
