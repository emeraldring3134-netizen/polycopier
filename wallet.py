from __future__ import annotations

import os
from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import encode_defunct


@dataclass
class WalletContext:
    address: str
    signature_type: int = 2


class Wallet:
    def __init__(self, private_key_env: str, signature_type: int = 2) -> None:
        private_key = os.getenv(private_key_env)
        if not private_key:
            raise ValueError(f"Missing private key in environment variable: {private_key_env}")
        self._private_key = private_key
        self._account = Account.from_key(private_key)
        self.context = WalletContext(address=self._account.address, signature_type=signature_type)

    @property
    def address(self) -> str:
        return self.context.address

    def sign_message(self, payload: str) -> str:
        msg = encode_defunct(text=payload)
        signed = self._account.sign_message(msg)
        return signed.signature.hex()
