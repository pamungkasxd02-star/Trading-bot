from types import SimpleNamespace

import pytest

from spotlab.market_browser import browse, coin_info, coverage
from spotlab.market_charts import MarketCharts
from spotlab.telegram_menu import route


def catalogue():
    rows = [
        dict(symbol=f"TOKEN{i}USDT", baseAsset=f"TOKEN{i}", quoteAsset="USDT") for i in range(75)
    ]
    rows.append(dict(symbol="TOKEN0BTC", baseAsset="TOKEN0", quoteAsset="BTC"))
    return {r["symbol"]: r for r in rows}


def account():
    metadata = {
        "learning_source": {"symbols": ["TOKEN1USDT"], "observed_at": "test-time"},
        "learning_universe": {
            "selected": [{"symbol": "TOKEN1USDT"}],
            "rejected": [{"symbol": "TOKEN0USDT", "reason": "insufficient_quote_volume"}],
        },
    }
    return SimpleNamespace(market=SimpleNamespace(metadata=lambda key: metadata.get(key, {})))


def test_pages_include_every_pair_once_and_exact_quote_filter():
    found = []
    for page in [1, 2, 3]:
        report, actual, quote = browse(catalogue(), "usdt", page)
        assert actual == page and quote == "USDT"
        found.extend(line.split("(")[1][:-1] for line in report.splitlines() if "(" in line)
        assert len(report) < 3900
    assert len(found) == 75 and len(set(found)) == 75
    assert "TOKEN0BTC" not in found
    assert browse(catalogue(), "ALL", 999)[1] == 3
    assert "TOKEN0BTC" in browse(catalogue(), "BTC")[0]
    with pytest.raises(ValueError):
        browse(catalogue(), "NONEXISTENT")


def test_snapshot_exclusions_do_not_hide_chart_pairs():
    report = coin_info(catalogue(), account(), "TOKEN0")
    assert "TOKEN0USDT" in report and "TOKEN0BTC" in report
    assert "volume quote" in report and "collector=tidak" in report
    assert "lolos scanner" in coin_info(catalogue(), account(), "TOKEN1USDT")
    report = coverage(catalogue(), account())
    assert "75 base asset unik | 76 pair" in report
    assert "Collector akun: 1 pair" in report
    assert "tidak berarti semua pair sedang direkam" in report


def test_paging_does_not_change_auto_or_prompt():
    state = {
        "auto": False,
        "market_browser": {"quote": "BTC", "page": 2},
        "menu_prompt": {"command": "/tradecoins", "expires": 1000},
    }
    assert route("Halaman berikut", state, 1)[0] == "/markets BTC 3"
    assert "menu_prompt" not in state and state["auto"] is False
    assert route("Halaman sebelumnya", {}, 1)[0] == "/markets USDT 1"


def test_catalogue_refresh_adds_new_listing_without_changing_execution(monkeypatch):
    info = {
        "symbols": [
            dict(
                symbol="OLDUSDT",
                baseAsset="OLD",
                quoteAsset="USDT",
                status="TRADING",
                isSpotTradingAllowed=True,
            )
        ]
    }
    clock = [1000.0]
    monkeypatch.setattr("spotlab.market_charts.time.monotonic", lambda: clock[0])
    charts = MarketCharts(SimpleNamespace(exchange_info=lambda: info))
    assert "NEWUSDT" not in charts.catalogue()
    info["symbols"].append(
        dict(
            symbol="NEWUSDT",
            baseAsset="NEW",
            quoteAsset="USDT",
            status="TRADING",
            isSpotTradingAllowed=True,
        )
    )
    assert "NEWUSDT" not in charts.catalogue()
    clock[0] += 901
    assert "NEWUSDT" in charts.catalogue()
