from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

from spotlab.config import AppConfig
from spotlab.exchange import BinanceRESTClient


@dataclass(frozen=True, slots=True)
class MarketCandidate:
    symbol: str
    quote_volume: float
    spread_bps: float


def spread_bps(book: dict[str, Any]) -> float:
    bid, ask = float(book.get("bidPrice", 0)), float(book.get("askPrice", 0))
    if not (isfinite(bid) and isfinite(ask) and 0 < bid <= ask):
        return float("inf")
    return (ask - bid) / ((ask + bid) / 2) * 10_000


def select_universe(
    config: AppConfig,
    info: dict[str, Any],
    tickers: list[dict[str, Any]],
    books: list[dict[str, Any]],
) -> tuple[list[MarketCandidate], list[dict[str, str]]]:
    """Screen current exchange metadata. Never reuse this snapshot as a past universe."""
    cfg = config.universe
    requested = (
        {config.exchange.symbol.upper()}
        if cfg.mode == "single"
        else set(cfg.symbols)
        if cfg.mode == "explicit"
        else None
    )
    volumes = {row["symbol"]: float(row.get("quoteVolume", 0)) for row in tickers}
    spreads = {row["symbol"]: spread_bps(row) for row in books}
    eligible, rejected, seen = [], [], set()
    for item in info.get("symbols", []):
        symbol = str(item["symbol"])
        if requested is not None and symbol not in requested:
            continue
        if item.get("quoteAsset") != cfg.quote_asset:
            continue
        seen.add(symbol)
        volume, spread = volumes.get(symbol, 0), spreads.get(symbol, float("inf"))
        reason = ""
        if item.get("status") != "TRADING" or not item.get("isSpotTradingAllowed", False):
            reason = "spot_not_trading"
        elif not item.get("ocoAllowed", False) or not {
            "MARKET",
            "STOP_LOSS_LIMIT",
            "TAKE_PROFIT_LIMIT",
        }.issubset(item.get("orderTypes", [])):
            reason = "market_or_oco_unavailable"
        elif item.get("baseAsset") in cfg.excluded_bases:
            reason = "excluded_base"
        elif not isfinite(volume) or volume < cfg.min_quote_volume:
            reason = "insufficient_quote_volume"
        elif spread > cfg.max_spread_bps:
            reason = "spread_or_book_unavailable"
        if reason:
            rejected.append({"symbol": symbol, "reason": reason})
        else:
            eligible.append(MarketCandidate(symbol, volume, spread))
    for symbol in sorted((requested or set()) - seen):
        rejected.append({"symbol": symbol, "reason": "symbol_unavailable"})
    eligible.sort(key=lambda item: (-item.quote_volume, item.symbol))
    if cfg.max_symbols is not None:
        rejected.extend(
            {"symbol": item.symbol, "reason": "universe_capacity"}
            for item in eligible[cfg.max_symbols :]
        )
        eligible = eligible[: cfg.max_symbols]
    return eligible, rejected


def discover_universe(client: BinanceRESTClient, config: AppConfig) -> dict[str, Any]:
    info = client.exchange_info()
    chosen, rejected = select_universe(config, info, client.tickers_24h(), client.book_ticker())
    return {
        "selected": [asdict(item) for item in chosen],
        "rejected": rejected,
        "exchange_info": info,
        "testnet": config.exchange.testnet,
    }
