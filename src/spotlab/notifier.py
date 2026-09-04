from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, enabled: bool) -> None:
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled

    def send(self, message: str) -> None:
        if not self.enabled:
            return
        if not self.token or not self.chat_id:
            raise RuntimeError("Telegram aktif tetapi token/chat id kosong")
        body = urlencode({"chat_id": self.chat_id, "text": message}).encode()
        request = Request(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            data=body,
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram notification failed: {payload}")
