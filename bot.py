#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POETRA AI Signal Bot — XAUUSD (+ forex/kripto opsional)
Analisa EMA/RSI/MACD/ATR + Fibonacci + struktur (smart-money sederhana),
hanya kirim sinyal HIGH-CONVICTION ke Telegram. Jalan di cloud (GitHub Actions).

ENV yang dibutuhkan (set sebagai GitHub Secrets / environment):
  TWELVE_DATA_KEY   -> API key dari https://twelvedata.com (gratis)
  TELEGRAM_TOKEN    -> token bot dari @BotFather
  TELEGRAM_CHAT_ID  -> chat id Anda (lihat panduan)
  SYMBOLS           -> opsional, default "XAU/USD". Bisa "XAU/USD,EUR/USD,BTC/USD"
  MIN_CONFIDENCE    -> opsional, default "70"
  SEND_WAIT         -> opsional "1" untuk kirim pesan walau tidak ada setup (default "0" = diam)
"""
import os, sys, time, json, urllib.parse, urllib.request, urllib.error

TD_KEY   = os.environ.get("TWELVE_DATA_KEY", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SYMBOLS  = [s.strip() for s in (os.environ.get("SYMBOLS") or "XAU/USD").split(",") if s.strip()]
MIN_CONF = float(os.environ.get("MIN_CONFIDENCE") or "70")
SEND_WAIT = (os.environ.get("SEND_WAIT") or "0") == "1"
INTERVAL = (os.environ.get("INTERVAL") or "15min")   # timeframe utama

def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "poetra-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def fetch_series(symbol, interval="15min", size=220):
    q = urllib.parse.urlencode({
        "symbol": symbol, "interval": interval, "outputsize": size,
        "apikey": TD_KEY, "format": "JSON"
    })
    data = http_get("https://api.twelvedata.com/time_series?" + q)
    if data.get("status") == "error" or "values" not in data:
        raise RuntimeError("Data error %s: %s" % (symbol, data.get("message", data)))
    vals = list(reversed(data["values"]))  # jadikan kronologis (lama -> baru)
    o = [float(v["open"]) for v in vals]
    h = [float(v["high"]) for v in vals]
    l = [float(v["low"]) for v in vals]
    c = [float(v["close"]) for v in vals]
    return o, h, l, c

# ---------- Indikator (murni Python, tanpa pandas) ----------
def ema(series, n):
    k = 2.0 / (n + 1)
    out = []
    prev = series[0]
    for x in series:
        prev = x * k + prev * (1 - k)
        out.append(prev)
    return out

def rsi(series, n=14):
    gains, losses = [0.0], [0.0]
    for i in range(1, len(series)):
        d = series[i] - series[i-1]
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag = sum(gains[1:n+1]) / n
    al = sum(losses[1:n+1]) / n
    out = [50.0] * len(series)
    for i in range(n+1, len(series)):
        ag = (ag * (n-1) + gains[i]) / n
        al = (al * (n-1) + losses[i]) / n
        rs = ag / al if al != 0 else 999
        out[i] = 100 - 100 / (1 + rs)
    return out

def macd(series, f=12, s=26, sig=9):
    ef, es = ema(series, f), ema(series, s)
    line = [a - b for a, b in zip(ef, es)]
    signal = ema(line, sig)
    hist = [a - b for a, b in zip(line, signal)]
    return line, signal, hist

def atr(h, l, c, n=14):
    trs = [h[0]-l[0]]
    for i in range(1, len(c)):
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    out = [trs[0]] * len(c)
    a = sum(trs[:n]) / n
    for i in range(n, len(c)):
        a = (a * (n-1) + trs[i]) / n
        out[i] = a
    return out

def fib_zone(h, l, lookback=60):
    seg_h, seg_l = h[-lookback:], l[-lookback:]
    hi = max(seg_h); lo = min(seg_l)
    hi_idx = len(seg_h) - 1 - seg_h[::-1].index(hi)
    lo_idx = len(seg_l) - 1 - seg_l[::-1].index(lo)
    up = lo_idx < hi_idx          # swing low lebih dulu -> leg naik
    rng = hi - lo if hi > lo else 1e-9
    if up:  # retracement support (untuk BUY)
        levels = {r: hi - rng * r for r in (0.382, 0.5, 0.618, 0.705, 0.786)}
    else:   # retracement resistance (untuk SELL)
        levels = {r: lo + rng * r for r in (0.382, 0.5, 0.618, 0.705, 0.786)}
    return up, hi, lo, levels

def analyze(symbol):
    o, h, l, c = fetch_series(symbol, INTERVAL)
    if len(c) < 60:
        return None
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    r = rsi(c, 14)
    ml, msg, mh = macd(c)
    a = atr(h, l, c, 14)
    up, hi, lo, fib = fib_zone(h, l, 60)
    px = c[-1]
    dec = lambda x: round(x, 2)

    trend_up = px > e200[-1] and e20[-1] > e50[-1]
    trend_dn = px < e200[-1] and e20[-1] < e50[-1]
    macd_up = mh[-1] > 0 and mh[-1] > mh[-2]
    macd_dn = mh[-1] < 0 and mh[-1] < mh[-2]
    rsi_buy = 45 <= r[-1] <= 68
    rsi_sell = 32 <= r[-1] <= 55
    gz_lo, gz_hi = fib[0.618], fib[0.705]
    in_disc = min(gz_lo, gz_hi) - a[-1] <= px <= max(gz_lo, gz_hi) + a[-1] or abs(px - e20[-1]) <= a[-1]

    bias, conf, reasons = "WAIT", 0, []
    if trend_up:
        conf += 35; reasons.append("Tren M15 naik (harga>EMA200, EMA20>EMA50)")
        if macd_up: conf += 20; reasons.append("MACD momentum naik")
        if rsi_buy: conf += 20; reasons.append("RSI sehat %.0f" % r[-1])
        if in_disc: conf += 25; reasons.append("Harga di zona diskon (Fib golden/EMA20)")
        if conf >= MIN_CONF: bias = "BUY"
    elif trend_dn:
        conf += 35; reasons.append("Tren M15 turun (harga<EMA200, EMA20<EMA50)")
        if macd_dn: conf += 20; reasons.append("MACD momentum turun")
        if rsi_sell: conf += 20; reasons.append("RSI %.0f" % r[-1])
        if in_disc: conf += 25; reasons.append("Harga di zona premium (Fib/EMA20)")
        if conf >= MIN_CONF: bias = "SELL"

    if bias == "BUY":
        sl = px - 1.6 * a[-1]; tp1 = px + 1.6 * a[-1]; tp2 = px + 3.2 * a[-1]
    elif bias == "SELL":
        sl = px + 1.6 * a[-1]; tp1 = px - 1.6 * a[-1]; tp2 = px - 3.2 * a[-1]
    else:
        sl = tp1 = tp2 = None

    res = {"symbol": symbol, "price": dec(px), "bias": bias, "conf": int(min(conf, 95)),
           "reasons": reasons, "rsi": round(r[-1], 1),
           "ema20": dec(e20[-1]), "ema50": dec(e50[-1]), "ema200": dec(e200[-1]),
           "atr": round(a[-1], 2)}
    if sl is not None:
        tp1p = abs(tp1 - px) / px * 100
        tp2p = abs(tp2 - px) / px * 100
        res.update({"sl": dec(sl), "tp1": dec(tp1), "tp2": dec(tp2),
                    "tp1pct": round(tp1p, 2), "tp2pct": round(tp2p, 2)})
    return res

def fmt(res):
    s = res["symbol"]
    reasons = "; ".join(res["reasons"]).replace("<", " di bawah ").replace(">", " di atas ")
    if res["bias"] in ("BUY", "SELL"):
        emo = "🟢" if res["bias"] == "BUY" else "🔴"
        msg = (
            "%s %s SIGNAL — %s\n"
            "Harga: %s | Confidence: %s%%\n"
            "━━━━━━━━━━━━━━\n"
            "Entry: %s\n"
            "Stop Loss: %s\n"
            "Take Profit 1: %s  (+%s%%)\n"
            "Take Profit 2: %s  (+%s%%)\n"
            "━━━━━━━━━━━━━━\n"
            "Alasan: %s\n"
            "RSI %s · EMA20 %s · EMA200 %s · ATR %s\n\n"
            "⚠️ Bukan nasihat keuangan. Maks 1%% risiko/trade, hormati Stop Loss."
        ) % (emo, s, res["bias"], res["price"], res["conf"], res["price"],
             res["sl"], res["tp1"], res["tp1pct"], res["tp2"], res["tp2pct"],
             reasons, res["rsi"], res["ema20"], res["ema200"], res["atr"])
    else:
        msg = ("⏳ %s — BELUM WAKTUNYA ENTRY (No-Trade Zone)\n"
               "Harga %s · konfluensi belum cukup kuat. Sabar, tunggu setup yakin.\n"
               "RSI %s · EMA20 %s · EMA200 %s") % (
               s, res["price"], res["rsi"], res["ema20"], res["ema200"])
    return msg

def send_telegram(text):
    url = "https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN
    body = urllib.parse.urlencode({
        "chat_id": TG_CHAT, "text": text,
        "disable_web_page_preview": "true"
    }).encode()
    req = urllib.request.Request(url, data=body)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("Telegram %s: %s" % (e.code, e.read().decode()))

def main():
    missing = [k for k, v in {"TWELVE_DATA_KEY": TD_KEY, "TELEGRAM_TOKEN": TG_TOKEN,
                              "TELEGRAM_CHAT_ID": TG_CHAT}.items() if not v]
    if missing:
        print("ENV belum lengkap:", missing); sys.exit(1)
    for sym in SYMBOLS:
        try:
            res = analyze(sym)
            if not res:
                print(sym, "data kurang"); continue
            print(sym, res["bias"], res["conf"])
            if res["bias"] in ("BUY", "SELL"):
                send_telegram(fmt(res))
            elif SEND_WAIT:
                send_telegram(fmt(res))
        except Exception as e:
            print("ERROR", sym, e)
        time.sleep(2)  # jaga rate limit

if __name__ == "__main__":
    main()
