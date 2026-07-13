#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POETRA AI Signal Bot v3 — 24/7 Telegram.
Fibonacci golden zone + arah tren + UT Bot(sensitif) + EMA/RSI/MACD.
Hanya kirim sinyal bila YAKIN (confidence >= MIN). Format ringkasan multi-timeframe.
ENV: TWELVE_DATA_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
     SYMBOLS (default "XAU/USD,BTC/USD,ETH/USD"), MIN_CONFIDENCE (default 80),
     SEND_WAIT ("1" utk kirim walau semua WAIT).
"""
import os, sys, time, json, datetime, urllib.parse, urllib.request, urllib.error

TD_KEY   = os.environ.get("TWELVE_DATA_KEY", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SYMBOLS  = [s.strip() for s in (os.environ.get("SYMBOLS") or "XAU/USD,BTC/USD,ETH/USD").split(",") if s.strip()]
MIN_CONF = float(os.environ.get("MIN_CONFIDENCE") or "80")
SEND_WAIT = (os.environ.get("SEND_WAIT") or "0") == "1"
TIMEFRAMES = [("M1", "1min"), ("M5", "5min"), ("M15", "15min")]

def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "poetra-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def fetch_series(symbol, interval, size=220):
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval,
                                "outputsize": size, "apikey": TD_KEY, "format": "JSON"})
    data = http_get("https://api.twelvedata.com/time_series?" + q)
    if data.get("status") == "error" or "values" not in data:
        raise RuntimeError("Data error %s %s: %s" % (symbol, interval, data.get("message", data)))
    vals = list(reversed(data["values"]))
    h = [float(v["high"]) for v in vals]
    l = [float(v["low"]) for v in vals]
    c = [float(v["close"]) for v in vals]
    return h, l, c

def ema(series, n):
    k = 2.0 / (n + 1); out = []; prev = series[0]
    for x in series:
        prev = x * k + prev * (1 - k); out.append(prev)
    return out

def rsi(series, n=14):
    gains, losses = [0.0], [0.0]
    for i in range(1, len(series)):
        d = series[i] - series[i-1]; gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag = sum(gains[1:n+1]) / n; al = sum(losses[1:n+1]) / n
    out = [50.0] * len(series)
    for i in range(n+1, len(series)):
        ag = (ag * (n-1) + gains[i]) / n; al = (al * (n-1) + losses[i]) / n
        rs = ag / al if al != 0 else 999; out[i] = 100 - 100 / (1 + rs)
    return out

def macd_hist(series, f=12, s=26, sig=9):
    ef, es = ema(series, f), ema(series, s)
    line = [a - b for a, b in zip(ef, es)]
    signal = ema(line, sig)
    return [a - b for a, b in zip(line, signal)]

def atr(h, l, c, n=14):
    trs = [h[0]-l[0]]
    for i in range(1, len(c)):
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    out = [trs[0]] * len(c); a = sum(trs[:n]) / n
    for i in range(n, len(c)):
        a = (a * (n-1) + trs[i]) / n; out[i] = a
    return out

def swing_fib(h, l, lb=80):
    sh, sl = h[-lb:], l[-lb:]
    hi = max(sh); lo = min(sl)
    hi_idx = len(sh) - 1 - sh[::-1].index(hi)
    lo_idx = len(sl) - 1 - sl[::-1].index(lo)
    up = lo_idx < hi_idx; rng = hi - lo if hi > lo else 1e-9
    def f(r): return hi - rng * r if up else lo + rng * r
    return {"up": up, "hi": hi, "lo": lo, "rng": rng, "l618": f(0.618), "l705": f(0.705)}

def ut_stops(h, l, c, key=0.8, ap=8):
    a = atr(h, l, c, ap); stop = [0.0]*len(c)
    for i in range(len(c)):
        nloss = key * a[i]
        if i == 0: stop[i] = c[i] - nloss; continue
        prev = stop[i-1]
        if c[i] > prev and c[i-1] > prev: stop[i] = max(prev, c[i]-nloss)
        elif c[i] < prev and c[i-1] < prev: stop[i] = min(prev, c[i]+nloss)
        elif c[i] > prev: stop[i] = c[i]-nloss
        else: stop[i] = c[i]+nloss
    return stop

def utbot(h, l, c):
    st = ut_stops(h, l, c, 0.8, 8)
    fb = c[-2] <= st[-2] and c[-1] > st[-1]
    fs = c[-2] >= st[-2] and c[-1] < st[-1]
    return {"pos": "BUY" if c[-1] > st[-1] else "SELL", "fresh": ("BUY" if fb else ("SELL" if fs else ""))}

def rnd(x):
    return round(x, 1) if abs(x) >= 100 else round(x, 4)

def analyze(symbol, interval):
    h, l, c = fetch_series(symbol, interval)
    if len(c) < 80:
        return {"bias": "WAIT", "conf": 0, "note": "data kurang", "utbot": "-", "rsi": "-", "dir": "RANGING"}
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    r = rsi(c, 14); mh = macd_hist(c); a = atr(h, l, c, 14)
    sf = swing_fib(h, l, 80); ub = utbot(h, l, c); px = c[-1]
    gz_lo = min(sf["l618"], sf["l705"]); gz_hi = max(sf["l618"], sf["l705"])
    in_gold = (gz_lo - a[-1]*0.6) <= px <= (gz_hi + a[-1]*0.6)
    bull = px > e200[-1] and e20[-1] > e50[-1]
    bear = px < e200[-1] and e20[-1] < e50[-1]
    dr = "BULLISH" if bull else ("BEARISH" if bear else "RANGING")
    m_up = mh[-1] > 0 and mh[-1] > mh[-2]; m_dn = mh[-1] < 0 and mh[-1] < mh[-2]
    r_buy = 45 <= r[-1] <= 68; r_sell = 32 <= r[-1] <= 55
    bias, conf = "WAIT", 0
    if bull and ub["pos"] == "BUY" and in_gold:
        conf = 45 + (20 if m_up else 0) + (15 if r_buy else 0) + (10 if ub["fresh"] == "BUY" else 0)
        if conf >= MIN_CONF: bias = "BUY"
    elif bear and ub["pos"] == "SELL" and in_gold:
        conf = 45 + (20 if m_dn else 0) + (15 if r_sell else 0) + (10 if ub["fresh"] == "SELL" else 0)
        if conf >= MIN_CONF: bias = "SELL"
    res = {"bias": bias, "conf": int(min(conf, 97)), "price": rnd(px), "rsi": round(r[-1], 1),
           "utbot": ub["pos"], "utbot_fresh": ub["fresh"], "dir": dr}
    if bias == "BUY":
        res.update(entry=rnd(px), sl=rnd(min(px-1.5*a[-1], gz_lo-0.3*a[-1])), tp1=rnd(sf["hi"]), tp2=rnd(sf["hi"]+0.618*sf["rng"]))
    elif bias == "SELL":
        res.update(entry=rnd(px), sl=rnd(max(px+1.5*a[-1], gz_hi+0.3*a[-1])), tp1=rnd(sf["lo"]), tp2=rnd(sf["lo"]-0.618*sf["rng"]))
    if "entry" in res:
        res["tp1pct"] = round(abs(res["tp1"]-res["entry"])/res["entry"]*100, 2)
        res["tp2pct"] = round(abs(res["tp2"]-res["entry"])/res["entry"]*100, 2)
    return res

def fmt_symbol(symbol, tf_res):
    price = next((tf_res[k]["price"] for k in ("M15","M5","M1") if tf_res.get(k, {}).get("price")), "-")
    lines = ["\U0001F4CA <b>%s</b>" % symbol, "Harga: %s" % price, "━"*10]
    best = None
    for tf in ("M1", "M5", "M15"):
        d = tf_res.get(tf, {}); b = d.get("bias", "WAIT")
        emo = "\U0001F7E2" if b == "BUY" else ("\U0001F534" if b == "SELL" else "⏸️")
        if b in ("BUY", "SELL"):
            lines.append("%s <b>%s %s</b> (conf %s%%) · UT Bot: %s" % (emo, tf, b, d.get("conf"), d.get("utbot")))
            lines.append("   Entry %s | SL %s | TP1 %s (+%s%%) | TP2 %s (+%s%%)" % (
                d.get("entry"), d.get("sl"), d.get("tp1"), d.get("tp1pct"), d.get("tp2"), d.get("tp2pct")))
            if best is None or d.get("conf", 0) > best[1]:
                best = (tf, d.get("conf", 0), b)
        else:
            lines.append("%s <b>%s WAIT</b> · UT Bot: %s (RSI %s)" % (emo, tf, d.get("utbot","-"), d.get("rsi","-")))
    lines.append("━"*10)
    lines.append("Metode: Fibonacci + EMA/RSI/MACD (high-conviction)")
    if best:
        lines.append("Keyakinan tertinggi: <b>%s%%</b> → ENTRY %s di %s" % (best[1], best[2], best[0]))
    else:
        lines.append("Keyakinan: belum ada setup ≥%d%% → WAIT" % int(MIN_CONF))
    lines.append("⚠️ Bukan nasihat keuangan. Maks 1% risiko/trade, hormati Stop Loss.")
    return "\n".join(lines)

def send_telegram(text):
    url = "https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN
    body = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text,
                                   "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("Telegram %s: %s" % (e.code, e.read().decode()))

def main():
    if not (TD_KEY and TG_TOKEN and TG_CHAT):
        print("ENV belum lengkap"); sys.exit(1)
    out = {"updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), "symbols": {}}
    for sym in SYMBOLS:
        tf_res = {}
        for tf_name, tf_int in TIMEFRAMES:
            try:
                tf_res[tf_name] = analyze(sym, tf_int)
            except Exception as e:
                print("ERR", sym, tf_name, e); tf_res[tf_name] = {"bias": "WAIT", "conf": 0}
            time.sleep(1)
        out["symbols"][sym] = tf_res
        actionable = any(tf_res[t].get("bias") in ("BUY", "SELL") for t in tf_res)
        print(sym, {t: tf_res[t].get("bias") for t in tf_res})
        if actionable or SEND_WAIT:
            try:
                send_telegram(fmt_symbol(sym, tf_res))
            except Exception as e:
                print("KIRIM GAGAL", sym, e)
        time.sleep(1)
    try:
        with open("signals.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("signals.json ditulis")
    except Exception as e:
        print("tulis signals.json gagal:", e)

if __name__ == "__main__":
    main()
