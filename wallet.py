from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import encode_defunct


@dataclass
class WalletContext:
    address: str
    signature_type: int = 2


class Wallet:
    def __init__(self, private_key: str, signature_type: int = 2) -> None:
        self._private_key = private_key
        self._account = Account.from_key(private_key)
        self.context = WalletContext(address=self._account.address, signature_type=signature_type)

    @property
    def address(self) -> str:
        return self.context.address

    @property
    def private_key(self) -> str:
        return self._private_key

    def sign_message(self, payload: str) -> str:
        msg = encode_defunct(text=payload)
        signed = self._account.sign_message(msg)
        return signed.signature.hex()
