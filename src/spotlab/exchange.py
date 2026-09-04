from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import websockets

LOGGER = logging.getLogger(__name__)

PRODUCTION_REST = "https://api.binance.com/api"
TESTNET_REST = "https://testnet.binance.vision/api"
PRODUCTION_WS = "wss://stream.binance.com:9443/ws"
TESTNET_WS = "wss://stream.testnet.binance.vision/ws"


class BinanceAPIError(RuntimeError):
    pass


class BinanceRESTClient:
    """Small, auditable Binance Spot REST client.

    Automatic retries are deliberately limited to GET. Retrying a timed-out
    order request without querying order state could create a duplicate order.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        *,
        testnet: bool = False,
        timeout: int = 15,
        recv_window_ms: int = 5000,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = TESTNET_REST if testnet else PRODUCTION_REST
        self.timeout = timeout
        self.recv_window_ms = recv_window_ms

    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        signed: bool = False,
    ) -> Any:
        payload = {key: value for key, value in (params or {}).items() if value is not None}
        if signed:
            if not self.api_key or not self.api_secret:
                raise BinanceAPIError("BINANCE_API_KEY dan BINANCE_API_SECRET wajib diisi")
            payload["timestamp"] = int(time.time() * 1000)
            payload["recvWindow"] = self.recv_window_ms
            query = urlencode(payload)
            payload["signature"] = hmac.new(
                self.api_secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()

        query = urlencode(payload)
        url = f"{self.base_url}{path}"
        body = None
        if method == "GET" and query:
            url = f"{url}?{query}"
        elif query:
            body = query.encode()

        headers = {"Accept": "application/json", "User-Agent": "binance-spot-lab/0.1"}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with urlopen(
                    Request(url, data=body, headers=headers, method=method), timeout=self.timeout
                ) as response:
                    return json.loads(response.read())
            except HTTPError as error:
                detail = error.read().decode(errors="replace")
                if method == "GET" and error.code in {418, 429, 500, 502, 503, 504}:
                    retry_after = float(error.headers.get("Retry-After", 2**attempt))
                    time.sleep(min(retry_after, 10))
                    continue
                raise BinanceAPIError(f"Binance HTTP {error.code}: {detail}") from error
            except (TimeoutError, URLError) as error:
                if attempt + 1 < attempts:
                    time.sleep(2**attempt)
                    continue
                raise BinanceAPIError(f"Binance request failed: {error}") from error
        raise BinanceAPIError("Binance request failed after retries")

    def server_time(self) -> dict[str, Any]:
        return self._request("GET", "/v3/time")

    def exchange_info(self, symbol: str) -> dict[str, Any]:
        return self._request("GET", "/v3/exchangeInfo", {"symbol": symbol.upper()})

    def klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 1000,
    ) -> list[list[Any]]:
        return self._request(
            "GET",
            "/v3/klines",
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time,
                "limit": min(limit, 1000),
            },
        )

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/v3/account", {"omitZeroBalances": "true"}, signed=True)

    def order(self, **params: Any) -> dict[str, Any]:
        return self._request("POST", "/v3/order", params, signed=True)

    def query_order(self, symbol: str, order_id: int | str) -> dict[str, Any]:
        return self._request(
            "GET", "/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True
        )

    def my_trades(self, symbol: str, order_id: int | str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/v3/myTrades",
            {"symbol": symbol, "orderId": order_id, "limit": 1000},
            signed=True,
        )

    def cancel_order_list(self, symbol: str, order_list_id: int | str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            "/v3/orderList",
            {"symbol": symbol, "orderListId": order_list_id},
            signed=True,
        )

    def create_oco(
        self,
        *,
        symbol: str,
        quantity: str,
        take_profit_price: str,
        stop_price: str,
        stop_limit_price: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v3/orderList/oco",
            {
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity,
                "aboveType": "TAKE_PROFIT_LIMIT",
                "aboveStopPrice": take_profit_price,
                "abovePrice": take_profit_price,
                "aboveTimeInForce": "GTC",
                "belowType": "STOP_LOSS_LIMIT",
                "belowStopPrice": stop_price,
                "belowPrice": stop_limit_price,
                "belowTimeInForce": "GTC",
                "newOrderRespType": "RESULT",
            },
            signed=True,
        )


async def stream_closed_klines(
    symbol: str,
    interval: str,
    *,
    testnet: bool,
    stop_event: asyncio.Event,
) -> AsyncIterator[dict[str, Any]]:
    """Yield only closed candles and reconnect with capped exponential backoff."""

    base = TESTNET_WS if testnet else PRODUCTION_WS
    url = f"{base}/{symbol.lower()}@kline_{interval}"
    delay = 1
    while not stop_event.is_set():
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=60, close_timeout=10, max_queue=256
            ) as socket:
                delay = 1
                while not stop_event.is_set():
                    raw = await asyncio.wait_for(socket.recv(), timeout=90)
                    message = json.loads(raw)
                    kline = message.get("k", {})
                    if kline.get("x"):
                        yield {
                            "open_time": int(kline["t"]),
                            "close_time": int(kline["T"]),
                            "open": float(kline["o"]),
                            "high": float(kline["h"]),
                            "low": float(kline["l"]),
                            "close": float(kline["c"]),
                            "volume": float(kline["v"]),
                        }
        except (TimeoutError, OSError, websockets.WebSocketException) as error:
            LOGGER.warning("WebSocket terputus (%s); reconnect dalam %ss", error, delay)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            delay = min(delay * 2, 30)
