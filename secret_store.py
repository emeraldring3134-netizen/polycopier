from __future__ import annotations

import base64
import getpass
import json
import os
import resource
import secrets as pysecrets
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


@dataclass
class SecretBundle:
    private_key: str
    funder: str


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _harden_process_memory() -> None:
    # best-effort hardening: disable core dump + lock memory
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        pass
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        libc.mlockall(1 | 2)  # MCL_CURRENT | MCL_FUTURE
        PR_SET_DUMPABLE = 4
        libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
    except Exception:
        pass


def init_secret_file(path: str) -> None:
    private_key = getpass.getpass("输入 MetaMask 私钥(0x...): ").strip()
    funder = input("输入代理钱包 funder 地址(0x...): ").strip()
    password = getpass.getpass("设置加密密码: ").strip()
    password2 = getpass.getpass("再次输入加密密码: ").strip()
    if password != password2:
        raise ValueError("两次密码不一致")
    if not private_key.startswith("0x") or len(private_key) < 66:
        raise ValueError("私钥格式错误")
    if not funder.startswith("0x"):
        raise ValueError("funder 地址格式错误")

    salt = pysecrets.token_bytes(16)
    key = _derive_key(password, salt)
    token = Fernet(key).encrypt(json.dumps({"private_key": private_key, "funder": funder}).encode("utf-8"))
    payload = {
        "version": 1,
        "kdf": "PBKDF2HMAC-SHA256",
        "iterations": 390000,
        "salt": base64.b64encode(salt).decode("ascii"),
        "ciphertext": token.decode("ascii"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)


def load_secret_file(path: str, password: str | None = None) -> SecretBundle:
    _harden_process_memory()
    with open(path, "r", encoding="utf-8") as f:
        payload: dict[str, Any] = json.load(f)

    pwd = password or getpass.getpass("输入解密密码: ").strip()
    salt = base64.b64decode(payload["salt"])
    key = _derive_key(pwd, salt)
    plain = Fernet(key).decrypt(payload["ciphertext"].encode("ascii"))
    data = json.loads(plain.decode("utf-8"))
    return SecretBundle(private_key=data["private_key"], funder=data["funder"])
