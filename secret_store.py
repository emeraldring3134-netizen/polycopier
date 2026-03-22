from __future__ import annotations

# base64 用于保存二进制盐值；getpass 用于无回显输入口令。
import base64
import getpass
import json
import os
import resource
import secrets as pysecrets
from dataclasses import dataclass
from typing import Any

# Fernet 负责对称加密；PBKDF2 用口令派生密钥。
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


@dataclass
class SecretBundle:
    """内存中的解密结果：私钥 + funder 地址。"""

    private_key: str
    funder: str


def _derive_key(password: str, salt: bytes) -> bytes:
    """用口令和盐值派生对称密钥。"""
    # 迭代次数取较高值以提高暴力破解成本。
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
    # Fernet 需要 URL-safe base64 编码的 32 字节密钥。
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _harden_process_memory() -> None:
    """best-effort 内存保护：禁 core dump + 尝试锁内存 + 禁止被 ptrace。"""
    try:
        # 禁止进程核心转储，减少敏感信息落盘风险。
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        pass
    try:
        # 使用 ctypes 调 libc，尽量锁住当前与未来内存页。
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        libc.mlockall(1 | 2)  # MCL_CURRENT | MCL_FUTURE
        # 设置进程不可被转储/调试（非绝对安全，属加固手段）。
        PR_SET_DUMPABLE = 4
        libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
    except Exception:
        pass


def init_secret_file(path: str) -> None:
    """交互录入私钥与 funder，并写入加密文件。"""
    # 私钥输入不回显。
    private_key = getpass.getpass("输入 MetaMask 私钥(0x...): ").strip()
    # funder 地址普通输入即可。
    funder = input("输入代理钱包 funder 地址(0x...): ").strip()
    # 输入加密口令并确认一次。
    password = getpass.getpass("设置加密密码: ").strip()
    password2 = getpass.getpass("再次输入加密密码: ").strip()
    if password != password2:
        raise ValueError("两次密码不一致")
    # 基础格式校验，避免写入错误数据。
    if not private_key.startswith("0x") or len(private_key) < 66:
        raise ValueError("私钥格式错误")
    if not funder.startswith("0x"):
        raise ValueError("funder 地址格式错误")

    # 生成随机盐值。
    salt = pysecrets.token_bytes(16)
    # 由口令派生密钥。
    key = _derive_key(password, salt)
    # 把私钥与 funder 序列化后加密。
    token = Fernet(key).encrypt(json.dumps({"private_key": private_key, "funder": funder}).encode("utf-8"))
    # 组装密文文件结构。
    payload = {
        "version": 1,
        "kdf": "PBKDF2HMAC-SHA256",
        "iterations": 390000,
        "salt": base64.b64encode(salt).decode("ascii"),
        "ciphertext": token.decode("ascii"),
    }
    # 仅保存密文，不保存明文私钥。
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # 设置严格文件权限，仅当前用户可读写。
    os.chmod(path, 0o600)


def load_secret_file(path: str, password: str | None = None) -> SecretBundle:
    """读取并解密密文文件，返回内存中的密钥包。"""
    # 解密前先做进程内存加固。
    _harden_process_memory()
    # 读取密文文件。
    with open(path, "r", encoding="utf-8") as f:
        payload: dict[str, Any] = json.load(f)

    # 未传入口令时走交互输入。
    pwd = password or getpass.getpass("输入解密密码: ").strip()
    # 恢复盐值并重新派生密钥。
    salt = base64.b64decode(payload["salt"])
    key = _derive_key(pwd, salt)
    # 解密得到明文 JSON。
    plain = Fernet(key).decrypt(payload["ciphertext"].encode("ascii"))
    data = json.loads(plain.decode("utf-8"))
    # 返回结构化对象，供上层初始化钱包与客户端。
    return SecretBundle(private_key=data["private_key"], funder=data["funder"])
