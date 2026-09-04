from decimal import Decimal

import pytest

from spotlab.execution.broker import BinanceBroker
from spotlab.models import SymbolRules


@pytest.fixture
def rules() -> SymbolRules:
    return SymbolRules(
        symbol="BTCUSDT",
        min_qty=Decimal("0.00001"),
        max_qty=Decimal("9000"),
        step_size=Decimal("0.00001"),
        tick_size=Decimal("0.01"),
        min_notional=Decimal("5"),
        max_notional=Decimal("9000000"),
    )


class AccountClient:
    def account(self):
        return {
            "canTrade": True,
            "balances": [
                {"asset": "BTC", "free": "0.25", "locked": "0.10"},
                {"asset": "USDT", "free": "1234.56", "locked": "78.90"},
            ],
        }


def test_broker_reads_dynamic_quote_balance(rules) -> None:
    broker = BinanceBroker(AccountClient(), rules, expected_testnet=True)
    balance = broker.asset_balance("usdt")
    assert balance.free == 1234.56
    assert balance.locked == 78.90
    assert balance.total == 1313.46


def test_missing_asset_is_zero_balance(rules) -> None:
    broker = BinanceBroker(AccountClient(), rules, expected_testnet=True)
    balance = broker.asset_balance("FDUSD")
    assert balance.total == 0.0
