"""Paginated active Spot catalogue, separate from collector/execution selection."""

from collections import Counter

from spotlab.market_charts import normalize_coin

REASONS = {
    "spot_not_trading": "pair tidak aktif untuk Spot",
    "market_or_oco_unavailable": "dukungan market/protection order belum sesuai",
    "excluded_base": "base masuk daftar pengecualian config",
    "insufficient_quote_volume": "volume quote di bawah batas config",
    "spread_or_book_unavailable": "spread terlalu besar atau book tidak tersedia",
    "universe_capacity": "batas jumlah coin pada config",
    "symbol_unavailable": "symbol tidak ditemukan",
}


def browse(catalogue, quote="USDT", page=1):
    quote = quote.upper()
    quotes = {r["quoteAsset"] for r in catalogue.values()}
    if quote != "ALL" and quote not in quotes:
        raise ValueError("Quote tidak ditemukan. Gunakan /markets ALL atau /coverage.")
    rows = sorted(
        (r for r in catalogue.values() if quote == "ALL" or r["quoteAsset"] == quote),
        key=lambda r: r["symbol"],
    )
    pages = max(1, (len(rows) + 29) // 30)
    page = min(max(1, page), pages)
    lines = [f"KATALOG SPOT {quote} | {len(rows)} pair | halaman {page}/{pages}"]
    lines.extend(
        f"{r['baseAsset']}/{r['quoteAsset']} ({r['symbol']})"
        for r in rows[(page - 1) * 30 : page * 30]
    )
    lines.append(
        "Ketik /coin TICKER untuk pasangan dan cakupan collector. "
        "Semua pair di sini dapat diminta chart; bukan daftar izin buy."
    )
    return "\n".join(lines), page, quote


def coverage(catalogue, account):
    counts = Counter(r["quoteAsset"] for r in catalogue.values())
    assets = {r["baseAsset"] for r in catalogue.values()}
    source = account.market.metadata("learning_source")
    selected = set(source.get("symbols", []))
    return (
        f"CAKUPAN BINANCE SPOT\n{len(assets)} base asset unik | {len(catalogue)} pair aktif\n"
        + "\n".join(f"{q}: {count} pair" for q, count in sorted(counts.items()))
        + f"\nCollector akun: {len(selected)} pair pada snapshot "
        + str(source.get("observed_at", "belum tersedia"))
        + "\nKatalog publik diperbarui saat diminta jika cache lewat 15 menit. "
        "Daftar collector hanya diperbarui saat startup, bukan otomatis mengikuti katalog. "
        "Grafik sesuai permintaan tidak berarti semua pair sedang direkam. "
        "Demo entry hanya USDT eligible; token di luar Binance Spot belum didukung."
    )


def coin_info(catalogue, account, query):
    coin = normalize_coin(query)
    if coin in catalogue:
        coin = catalogue[coin]["baseAsset"]
    pairs = sorted(
        (r for r in catalogue.values() if r["baseAsset"] == coin), key=lambda r: r["symbol"]
    )
    if not pairs:
        return "Coin/pair tidak ditemukan di Spot aktif. Gunakan ticker; /coins untuk pencarian."
    source = account.market.metadata("learning_source")
    universe = account.market.metadata("learning_universe")
    collected = set(source.get("symbols", []))
    selected = {r["symbol"] for r in universe.get("selected", [])}
    rejected = {r["symbol"]: r["reason"] for r in universe.get("rejected", [])}
    lines = [
        f"COIN {coin} | {len(pairs)} pasangan aktif",
        f"Snapshot scanner: {universe.get('observed_at', 'belum tersedia')}",
    ]
    for row in pairs[:30]:
        symbol = row["symbol"]
        reason = (
            "lolos scanner startup"
            if symbol in selected
            else REASONS.get(rejected.get(symbol), "belum masuk snapshot scanner akun")
        )
        if row["quoteAsset"] != "USDT":
            reason = "chart/analisis saja; demo entry hanya USDT"
        lines.append(f"{symbol}: {reason}; collector={'ya' if symbol in collected else 'tidak'}")
    if len(pairs) > 30:
        lines.append("Tampilan dibatasi 30 pasangan; gunakan /coins " + coin)
    lines.append(
        f"/chart {pairs[0]['symbol']} 15m | /techniques {pairs[0]['symbol']} 15m\n"
        "Status snapshot bukan izin buy sekarang; pilihan tradecoins/risk tetap diperiksa."
    )
    return "\n".join(lines)
