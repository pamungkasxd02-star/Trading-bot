from spotlab.execution.broker import BinanceBroker


class LiveBroker(BinanceBroker):
    """Production adapter with an additional credential-safety check."""

    def validate_account(self) -> None:
        if self.expected_testnet:
            raise RuntimeError("Live broker menolak endpoint testnet")
        account = self.client.account()
        if not account.get("canTrade", False):
            raise RuntimeError("API key tidak memiliki izin trading")
        if account.get("canWithdraw", False):
            raise RuntimeError("LIVE BLOCKED: API key masih memiliki izin withdrawal")
