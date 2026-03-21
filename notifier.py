from __future__ import annotations

import aiohttp


class FeishuNotifier:
    def __init__(self, webhook: str) -> None:
        self.webhook = webhook

    async def send_text(self, text: str) -> None:
        if not self.webhook:
            return
        payload = {"msg_type": "text", "content": {"text": text}}
        async with aiohttp.ClientSession() as session:
            async with session.post(self.webhook, json=payload):
                return
