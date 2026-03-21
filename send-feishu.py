#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

import aiohttp


async def send(webhook: str, text: str) -> None:
    payload = {"msg_type": "text", "content": {"text": text}}
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook, json=payload) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"feishu failed: {resp.status}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook", required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    asyncio.run(send(args.webhook, args.text))


if __name__ == "__main__":
    main()
