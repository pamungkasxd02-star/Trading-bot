from decimal import Decimal

from spotlab.data import MarketDataStore, parse_symbol_rules


def test_parse_and_persist_real_exchange_filters(tmp_path) -> None:
    payload = {
        "symbols": [
            {
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.00001000",
                        "maxQty": "9000.00000000",
                        "stepSize": "0.00001000",
                    },
                    {
                        "filterType": "NOTIONAL",
                        "minNotional": "5.00000000",
                        "maxNotional": "9000000.00000000",
                    },
                ]
            }
        ]
    }
    parsed = parse_symbol_rules(payload, "BTCUSDT")
    store = MarketDataStore(tmp_path / "market.db")
    store.save_symbol_rules(parsed)
    loaded = store.load_symbol_rules("BTCUSDT")
    assert loaded.step_size == Decimal("0.00001000")
    assert loaded.min_notional == Decimal("5.00000000")


def test_candle_upsert_is_idempotent(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "market.db")
    candle = [1, "10", "12", "9", "11", "100", 2, "1000", 20]
    store.upsert_klines("BTCUSDT", "4h", [candle])
    candle[4] = "11.5"
    store.upsert_klines("BTCUSDT", "4h", [candle])
    frame = store.load_candles("BTCUSDT", "4h")
    assert len(frame) == 1
    assert frame.iloc[0]["close"] == 11.5
