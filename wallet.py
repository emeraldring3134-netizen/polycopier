from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import encode_defunct


@dataclass
class WalletContext:
    address: str
    signature_type: int = 2


class Wallet:
    def __init__(
        self,
        private_key_env: str,
        signature_type: int = 2,
        private_key_gpg: str | None = ".env.gpg",
    ) -> None:
        private_key = self._load_private_key(private_key_env=private_key_env, private_key_gpg=private_key_gpg)
        self._private_key = private_key
        self._account = Account.from_key(private_key)
        self.context = WalletContext(address=self._account.address, signature_type=signature_type)

    def _load_private_key(self, private_key_env: str, private_key_gpg: str | None) -> str:
        if private_key_gpg and os.path.exists(private_key_gpg):
            out = subprocess.check_output(["gpg", "--decrypt", private_key_gpg], text=True)
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("PRIVATE_KEY="):
                    return line.split("=", 1)[1].strip()
                if line.startswith("0x") and len(line) >= 66:
                    return line

        private_key = os.getenv(private_key_env)
        if not private_key:
            raise ValueError(
                f"Missing private key: put encrypted key in {private_key_gpg} or set env {private_key_env}"
            )
        return private_key

    @property
    def address(self) -> str:
        return self.context.address

    def sign_message(self, payload: str) -> str:
        msg = encode_defunct(text=payload)
        signed = self._account.sign_message(msg)
        return signed.signature.hex()

    @property
    def private_key(self) -> str:
        return self._private_key
