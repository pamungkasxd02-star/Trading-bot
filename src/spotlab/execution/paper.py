from spotlab.execution.broker import BinanceBroker


class TestnetPaperBroker(BinanceBroker):
    """Exchange-backed paper trading. It must use Binance Spot Testnet."""

    def validate_account(self) -> None:
        if not self.expected_testnet:
            raise RuntimeError("Paper broker menolak endpoint production")
        super().validate_account()
