"""Hypothetical sizing from closed candles; no order submission or pending state."""

from spotlab.data import parse_symbol_rules
from spotlab.indicators import atr
from spotlab.risk import RiskManager, RiskViolation
from spotlab.strategy_review import evaluate


def preview(account, charts, query, interval):
    market, frame = charts.candles(query, interval)
    if market["quoteAsset"] != "USDT":
        return "Rencana demo hanya untuk pair USDT; saldo akun dihitung dalam USDT."
    cfg = account.config
    status = account.status()
    symbol = market["symbol"]
    evaluation = evaluate(frame, cfg.strategy, cfg.strategy.name)
    blockers = []
    if cfg.demo.analysis_only:
        blockers.append("mode belajar tanpa order")
    if not status.get("telegram_control", {}).get("auto", True):
        blockers.append("auto entry dijeda")
    if status["trading_halted"]:
        blockers.append("risk halt/kill-switch")
    if status["position"]:
        blockers.append("posisi lain masih terbuka")
    if status["health"] != "healthy":
        blockers.append("data/collector belum sehat")
    eligible = account.market.metadata("learning_source").get("symbols", [])
    chosen = status.get("telegram_control", {}).get("tradecoins", [])
    if symbol not in eligible or (chosen and symbol not in chosen):
        blockers.append("coin di luar pilihan entry eligible")
    if interval != cfg.demo.interval:
        blockers.append("timeframe berbeda dari engine demo")
    if evaluation["state"] != "SETUP ENTRY":
        blockers.append("strategi belum menghasilkan setup entry siap")
    fee = cfg.backtest.fee_bps / 10000
    slip = cfg.backtest.slippage_bps / 10000
    last = frame.iloc[-1]
    entry = float(last.close) * (1 + slip)
    lines = [
        f"RENCANA HIPOTETIS {symbol} | {interval}",
        f"Candle tutup UTC: {last.close_time.isoformat()}",
        f"Strategi: {cfg.strategy.name} | {evaluation['state']}",
        evaluation["detail"],
        "Hambatan: "
        + (", ".join(blockers) if blockers else "belum terlihat; pemeriksaan terbatas"),
        "Acuan dari CLOSE candle + slippage, BUKAN harga ask/order live.",
    ]
    try:
        rules = parse_symbol_rules({"symbols": [market]}, symbol)
        sized = RiskManager(cfg.risk, rules).size_long(
            status["cash"],
            entry,
            status["cash"] / (1 + fee),
            atr_value=float(atr(frame, cfg.strategy.atr_period).iloc[-1]),
            cost_bps=2 * (cfg.backtest.fee_bps + cfg.backtest.slippage_bps),
        )
    except RiskViolation as exc:
        return "\n".join([*lines, f"Sizing ditolak: {exc}", "Tidak membuat order."])
    qty = float(sized.quantity)
    stop, target = float(sized.stop_price), float(sized.take_profit_price)
    stop_fill, target_fill = stop * (1 - slip), target * (1 - slip)
    net_loss = qty * (entry - stop_fill) + qty * fee * (entry + stop_fill)
    net_gain = qty * (target_fill - entry) - qty * fee * (entry + target_fill)
    ratio = net_gain / net_loss if net_loss > 0 else 0
    if qty > float(last.volume) * cfg.risk.max_candle_participation_pct / 100:
        lines.append("Sizing melebihi batas partisipasi volume; engine harus menolak.")
    lines.extend(
        [
            f"Acuan buy simulasi: {entry:.8g} USDT | quantity: {qty:.8g}",
            f"Notional: {float(sized.notional):.4f} USDT | fee entry: {qty * entry * fee:.4f}",
            f"SL trigger: {stop:.8g} | TP trigger: {target:.8g}",
            f"Estimasi loss ke SL: {net_loss:.4f} USDT | PnL ke TP: {net_gain:.4f} USDT",
            f"Rasio net TP/loss: {ratio:.2f} | fee/slippage per sisi: "
            f"{cfg.backtest.fee_bps}/{cfg.backtest.slippage_bps} bps",
            "Asumsi fill di trigger dengan slippage tetap; gap dapat memperbesar loss. "
            "Spread aktual, depth, pajak dan fresh-price gate belum dimodelkan di preview. "
            "Tidak mengirim BUY/SELL, tidak mengubah pending atau auto-buy.",
        ]
    )
    return "\n".join(lines)
