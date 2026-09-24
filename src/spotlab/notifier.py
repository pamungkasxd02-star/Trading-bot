from __future__ import annotations

import json
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class PhotoDeliveryError(RuntimeError):
    def __init__(self, retry_after=60):
        super().__init__("Telegram photo failed; inspect access/network privately")
        self.retry_after = max(60, min(86400, int(retry_after)))


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
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read())
            if not payload.get("ok"):
                raise RuntimeError("Telegram rejected message")
        except Exception:
            raise RuntimeError(
                "Telegram message failed; details hidden to protect credentials"
            ) from None

    def send_photo(self, png: bytes, caption: str) -> None:
        if not self.enabled:
            return
        if not self.token or not self.chat_id:
            raise RuntimeError("Telegram token/chat id belum tersedia")
        boundary = uuid.uuid4().hex
        parts = []
        for key, value in {
            "chat_id": self.chat_id,
            "caption": caption,
            "protect_content": "true",
        }.items():
            parts.append(
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
                    f"\r\n\r\n{value}\r\n"
                ).encode()
            )
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
                'filename="candle.png"\r\nContent-Type: image/png\r\n\r\n'
            ).encode()
            + png
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        try:
            request = Request(
                f"https://api.telegram.org/bot{self.token}/sendPhoto",
                data=b"".join(parts),
                method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read())
            if not payload.get("ok"):
                raise RuntimeError("Telegram rejected photo")
        except HTTPError as exc:
            delay = 300
            try:
                body = json.loads(exc.read())
                delay = int(body.get("parameters", {}).get("retry_after", delay))
            except (ValueError, TypeError, AttributeError):
                pass
            raise PhotoDeliveryError(delay) from None
        except Exception:
            raise PhotoDeliveryError() from None
