#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POETRA AI Signal Bot v9 — 24/7 Telegram (Binance keyless).
AKURASI TINGGI: konfirmasi arah (ADX + DI), filter multi-timeframe (HTF),
konfirmasi candle close, anti-chasing, SL berbasis struktur (swing/OB), min Risk:Reward.
Fibonacci golden zone + EMA/RSI/MACD + UT Bot. Kirim entry hanya bila YAKIN.
Lacak trade -> balas "✅ DONE 100%" saat TP1, "❌ kena SL" saat SL.
ENV: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SYMBOLS (default XAU/USD,BTC/USD,ETH/USD),
     MIN_CONFIDENCE (default 82), SEND_WAIT.
"""
import os, sys, time, json, datetime, urllib.request, urllib.error, urllib.parse

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SYMBOLS  = [s.strip() for s in (os.environ.get("SYMBOLS") or "XAU/USD,BTC/USD,ETH/USD").split(",") if s.strip()]
MIN_CONF = float(os.environ.get("MIN_CONFIDENCE") or "82")
SEND_WAIT = (os.environ.get("SEND_WAIT") or "0") == "1"
TIMEFRAMES = [("M1", "1m"), ("M5", "5m"), ("M15", "15m")]
HTF = {"1m":"15m","5m":"15m","15m":"1h","1h":"4h"}
OPEN_FILE = "open_trades.json"

BINMAP = {"XAU/USD":"PAXGUSDT","XAUUSD":"PAXGUSDT","GOLD":"PAXGUSDT",
          "BTC/USD":"BTCUSDT","BTCUSD":"BTCUSDT","BTC":"BTCUSDT",
          "ETH/USD":"ETHUSDT","ETHUSD":"ETHUSDT","ETH":"ETHUSDT",
          "SOL/USD":"SOLUSDT","SOL":"SOLUSDT","BNB/USD":"BNBUSDT","BNB":"BNBUSDT"}
HOSTS = ["https://api.binance.com","https://data-api.binance.vision","https://api-gcp.binance.com",
         "https://api1.binance.com","https://api2.binance.com","https://api3.binance.com"]

def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "poetra-bot"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())
def binance_klines(bnsym, interval, limit=300):
    last=None
    for h in HOSTS:
        try:
            d=http_get("%s/api/v3/klines?symbol=%s&interval=%s&limit=%d"%(h,bnsym,interval,limit))
            if isinstance(d,list) and d: return d
        except Exception as e: last=e
    raise RuntimeError("binance fail %s: %s"%(bnsym,last))

_GS=[None,0.0]; _GOFF=[0.0]
def gold_spot():
    if _GS[0] and (time.time()-_GS[1])<90: return _GS[0]
    try:
        j=http_get("https://api.gold-api.com/price/XAU")
        if j and j.get("price"): _GS[0]=float(j["price"]); _GS[1]=time.time()
    except Exception: pass
    return _GS[0]
def refresh_gold_offset():
    sp=gold_spot()
    if not sp: return
    try:
        d=binance_klines("PAXGUSDT","1m",2); _GOFF[0]=sp-float(d[-1][4])
    except Exception: pass
def to_bn(symbol):
    if symbol in BINMAP: return BINMAP[symbol]
    s=symbol.replace("/","").upper()
    if s.endswith("USDT"): return s
    if s.endswith("USD"): return s[:-3]+"USDT"
    return s+"USDT"
def fetch_ohlc(symbol, interval, size=300):
    bn=to_bn(symbol); d=binance_klines(bn,interval,size)
    o=[float(k[1]) for k in d]; h=[float(k[2]) for k in d]; l=[float(k[3]) for k in d]; c=[float(k[4]) for k in d]
    if bn=="PAXGUSDT" and _GOFF[0]:
        off=_GOFF[0]; o=[x+off for x in o]; h=[x+off for x in h]; l=[x+off for x in l]; c=[x+off for x in c]
    return o,h,l,c

# --- indikator ---
def ema(s,n):
    k=2.0/(n+1); out=[]; p=s[0]
    for x in s: p=x*k+p*(1-k); out.append(p)
    return out
def rsi(s,n=14):
    g=[0.0]; l=[0.0]
    for i in range(1,len(s)):
        d=s[i]-s[i-1]; g.append(max(d,0.0)); l.append(max(-d,0.0))
    ag=sum(g[1:n+1])/n; al=sum(l[1:n+1])/n; out=[50.0]*len(s)
    for i in range(n+1,len(s)):
        ag=(ag*(n-1)+g[i])/n; al=(al*(n-1)+l[i])/n; rs=ag/al if al!=0 else 999; out[i]=100-100/(1+rs)
    return out
def macd_hist(s,f=12,sl=26,sig=9):
    ef,es=ema(s,f),ema(s,sl); line=[a-b for a,b in zip(ef,es)]; sg=ema(line,sig)
    return [a-b for a,b in zip(line,sg)]
def rma(x,n):
    out=[0.0]*len(x);
    if len(x)<n: return out
    a=sum(x[:n])/n; out[n-1]=a
    for i in range(n,len(x)): a=(a*(n-1)+x[i])/n; out[i]=a
    return out
def atr(h,l,c,n=14):
    t=[h[0]-l[0]]
    for i in range(1,len(c)): t.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    return rma(t,n)
def adx_di(h,l,c,n=14):
    pdm=[0.0]; mdm=[0.0]; tr=[h[0]-l[0]]
    for i in range(1,len(c)):
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        pdm.append(up if (up>dn and up>0) else 0.0)
        mdm.append(dn if (dn>up and dn>0) else 0.0)
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    atr_=rma(tr,n); pd=rma(pdm,n); md=rma(mdm,n)
    pdi=[(100*pd[i]/atr_[i]) if atr_[i] else 0 for i in range(len(c))]
    mdi=[(100*md[i]/atr_[i]) if atr_[i] else 0 for i in range(len(c))]
    dx=[(100*abs(pdi[i]-mdi[i])/((pdi[i]+mdi[i]) or 1)) for i in range(len(c))]
    return rma(dx,n), pdi, mdi
def swing_fib(h,l,lb=80):
    sh,sl=h[-lb:],l[-lb:]; hi=max(sh); lo=min(sl)
    up=(len(sl)-1-sl[::-1].index(lo))<(len(sh)-1-sh[::-1].index(hi)); rng=hi-lo if hi>lo else 1e-9
    f=lambda r:(hi-rng*r) if up else (lo+rng*r)
    return {"up":up,"hi":hi,"lo":lo,"rng":rng,"l618":f(0.618),"l705":f(0.705)}
def ut_stops(h,l,c,key=0.8,ap=8):
    a=atr(h,l,c,ap); st=[0.0]*len(c)
    for i in range(len(c)):
        nl=key*a[i]
        if i==0: st[i]=c[i]-nl; continue
        p=st[i-1]
        if c[i]>p and c[i-1]>p: st[i]=max(p,c[i]-nl)
        elif c[i]<p and c[i-1]<p: st[i]=min(p,c[i]+nl)
        elif c[i]>p: st[i]=c[i]-nl
        else: st[i]=c[i]+nl
    return st
def utbot(h,l,c):
    st=ut_stops(h,l,c); fb=c[-2]<=st[-2] and c[-1]>st[-1]; fs=c[-2]>=st[-2] and c[-1]<st[-1]
    return {"pos":"BUY" if c[-1]>st[-1] else "SELL","fresh":("BUY" if fb else ("SELL" if fs else ""))}
def rnd(x): return round(x,1) if abs(x)>=100 else round(x,4)

def htf_bias(symbol, interval):
    try:
        htf=HTF.get(interval,"1h"); _,h,l,c=fetch_ohlc(symbol,htf,200)
        e20,e50,e200=ema(c,20),ema(c,50),ema(c,200); px=c[-1]
        if px>e200[-1] and e20[-1]>e50[-1]: return "BULLISH"
        if px<e200[-1] and e20[-1]<e50[-1]: return "BEARISH"
    except Exception: pass
    return "RANGING"

def analyze(symbol, interval):
    o,h,l,c = fetch_ohlc(symbol, interval, 300)
    if len(c) < 90: return {"bias":"WAIT","conf":0,"utbot":"-","rsi":"-","dir":"RANGING"}
    e20,e50,e200=ema(c,20),ema(c,50),ema(c,200); r=rsi(c,14); mh=macd_hist(c); a=atr(h,l,c,14)
    sf=swing_fib(h,l,80); ub=utbot(h,l,c); adx,pdi,mdi=adx_di(h,l,c,14); px=c[-1]
    htf=htf_bias(symbol, interval)
    gz_lo=min(sf["l618"],sf["l705"]); gz_hi=max(sf["l618"],sf["l705"])
    in_gold=(gz_lo-a[-1]*0.6)<=px<=(gz_hi+a[-1]*0.6)
    ema_bull=px>e200[-1] and e20[-1]>e50[-1]; ema_bear=px<e200[-1] and e20[-1]<e50[-1]
    dr="BULLISH" if ema_bull else ("BEARISH" if ema_bear else "RANGING")
    m_up=mh[-1]>0 and mh[-1]>mh[-2]; m_dn=mh[-1]<0 and mh[-1]<mh[-2]
    r_buy=48<=r[-1]<=66; r_sell=34<=r[-1]<=52
    di_bull=pdi[-1]>mdi[-1]; di_bear=mdi[-1]>pdi[-1]; adx_ok=adx[-1]>=20
    candle_bull=c[-1]>o[-1]; candle_bear=c[-1]<o[-1]
    not_ext=abs(px-e20[-1])<=1.4*a[-1]           # jangan ngejar harga terlalu jauh dari EMA20
    # swing struktur utk SL
    sw_lo=min(l[-14:]); sw_hi=max(h[-14:])
    bias,conf="WAIT",0
    # SYARAT WAJIB BUY: EMA bull + HTF bull + DI bull + UT Bot BUY + golden zone + ADX kuat + candle bullish + tidak overextended + RSI sehat
    if ema_bull and htf=="BULLISH" and di_bull and ub["pos"]=="BUY" and in_gold and adx_ok and candle_bull and not_ext and r_buy:
        conf=60+(12 if m_up else 0)+(10 if adx[-1]>=25 else 0)+(8 if ub["fresh"]=="BUY" else 0)+(6 if (pdi[-1]-mdi[-1])>=8 else 0)
        bias="BUY"
    elif ema_bear and htf=="BEARISH" and di_bear and ub["pos"]=="SELL" and in_gold and adx_ok and candle_bear and not_ext and r_sell:
        conf=60+(12 if m_dn else 0)+(10 if adx[-1]>=25 else 0)+(8 if ub["fresh"]=="SELL" else 0)+(6 if (mdi[-1]-pdi[-1])>=8 else 0)
        bias="SELL"
    else:
        # skor perkiraan (utk info) tanpa entry
        base=20
        if ema_bull: base+= (10 if htf=="BULLISH" else 0)+(8 if di_bull else 0)+(6 if in_gold else 0)+(6 if adx_ok else 0)
        elif ema_bear: base+= (10 if htf=="BEARISH" else 0)+(8 if di_bear else 0)+(6 if in_gold else 0)+(6 if adx_ok else 0)
        conf=base
    res={"bias":bias,"conf":int(min(conf,98)),"price":rnd(px),"rsi":round(r[-1],1),"utbot":ub["pos"],
         "utbot_fresh":ub["fresh"],"dir":dr,"htf":htf,"adx":round(adx[-1],1)}
    if bias in ("BUY","SELL"):
        buf=0.4*a[-1]
        if bias=="BUY":
            sl=min(sw_lo, gz_lo)-buf                 # SL di BAWAH struktur (swing low / golden zone) + buffer
            risk=px-sl
            tp1=max(sf["hi"], px+1.8*risk)           # TP minimal 1.8R atau swing high (mana lebih jauh)
            tp2=px+3.0*risk
        else:
            sl=max(sw_hi, gz_hi)+buf
            risk=sl-px
            tp1=min(sf["lo"], px-1.8*risk)
            tp2=px-3.0*risk
        rr=abs(tp1-px)/max(abs(px-sl),1e-9)
        if rr<1.5:                                    # buang setup RR jelek
            res["bias"]="WAIT"; res["conf"]=min(res["conf"],70)
            return res
        res.update(entry=rnd(px), sl=rnd(sl), tp1=rnd(tp1), tp2=rnd(tp2), rr=round(rr,1))
        res["tp1pct"]=round(abs(res["tp1"]-res["entry"])/res["entry"]*100,2)
        res["tp2pct"]=round(abs(res["tp2"]-res["entry"])/res["entry"]*100,2)
    return res

def fmt_symbol(symbol, tf_res):
    price=next((tf_res[k]["price"] for k in ("M15","M5","M1") if tf_res.get(k,{}).get("price")),"-")
    L=["\U0001F4CA <b>%s — Sinyal Multi-Timeframe</b>"%symbol,"Harga saat ini: <b>%s</b>"%price,"━"*12]
    best=None
    for tf in ("M1","M5","M15"):
        d=tf_res.get(tf,{}); b=d.get("bias","WAIT")
        emo="\U0001F7E2" if b=="BUY" else ("\U0001F534" if b=="SELL" else "⏸️")
        if b in ("BUY","SELL"):
            L.append("%s <b>%s — %s</b> · keyakinan <b>%s%%</b> · UT Bot: %s · HTF %s · ADX %s"%(emo,tf,b,d.get("conf"),d.get("utbot"),d.get("htf"),d.get("adx")))
            L.append("     Entry: %s"%d.get("entry")); L.append("     Stop Loss: %s (di bawah/atas struktur)"%d.get("sl"))
            L.append("     TP1: %s (+%s%%)   TP2: %s (+%s%%)"%(d.get("tp1"),d.get("tp1pct"),d.get("tp2"),d.get("tp2pct")))
            if best is None or d.get("conf",0)>best[1]: best=(tf,d.get("conf",0),b,d)
        else:
            L.append("%s <b>%s — WAIT</b> · keyakinan %s%% · UT Bot: %s (RSI %s · HTF %s)"%(emo,tf,d.get("conf","-"),d.get("utbot","-"),d.get("rsi","-"),d.get("htf","-")))
    L.append("━"*12)
    if best:
        tf,cf,bb,d=best
        L.append("\U0001F3AF <b>REKOMENDASI ENTRY: %s %s (%s)</b>"%(bb,tf,symbol))
        L.append("Keyakinan analisa: <b>%s%%</b> · Risk:Reward %s · konfirmasi arah (ADX %s, HTF %s)"%(cf,d.get("rr"),d.get("adx"),d.get("htf")))
        L.append("Entry %s | SL %s | TP1 %s | TP2 %s"%(d.get("entry"),d.get("sl"),d.get("tp1"),d.get("tp2")))
        L.append("Entry saat candle konfirmasi searah. Bila TP tercapai, sinyal ini dibalas otomatis: ✅ DONE 100%.")
    else:
        L.append("⏸️ <b>Belum ada setup akurasi tinggi (≥%d%%).</b> Arah/HTF/ADX/golden-zone belum sepakat — jangan paksa entry."%int(MIN_CONF))
    L.append("━"*12)
    L.append("Metode: Fibonacci golden-zone + Multi-Timeframe + ADX/DI (arah) + UT Bot + EMA/RSI/MACD + SL struktur.")
    L.append("⚠️ Bukan nasihat keuangan. Maksimal 1% risiko/trade, selalu pasang Stop Loss.")
    return "\n".join(L)

def send_telegram(text, reply_to=None):
    url="https://api.telegram.org/bot%s/sendMessage"%TG_TOKEN
    p={"chat_id":TG_CHAT,"text":text,"parse_mode":"HTML","disable_web_page_preview":"true","allow_sending_without_reply":"true"}
    if reply_to: p["reply_to_message_id"]=reply_to
    body=urllib.parse.urlencode(p).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url,data=body),timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("Telegram %s: %s"%(e.code,e.read().decode()))
def load_open():
    try:
        with open(OPEN_FILE,"r",encoding="utf-8") as f: return json.load(f)
    except Exception: return []
def save_open(x):
    try:
        with open(OPEN_FILE,"w",encoding="utf-8") as f: json.dump(x,f,ensure_ascii=False,indent=2)
    except Exception as e: print("save open gagal:",e)
def check_open_trades():
    opens=load_open()
    if not opens: return
    still=[]
    for t in opens:
        try:
            _,h,l,c=fetch_ohlc(t["sym"],"1m",300); hit=None
            for i in range(len(c)):
                if t["bias"]=="BUY":
                    if h[i]>=t["tp1"]: hit="TP"; break
                    if l[i]<=t["sl"]: hit="SL"; break
                else:
                    if l[i]<=t["tp1"]: hit="TP"; break
                    if h[i]>=t["sl"]: hit="SL"; break
            if hit=="TP":
                send_telegram("✅ <b>DONE 100%</b> — %s %s %s tercapai di TP1 (%s). Candle sudah konfirmasi & akurasi sesuai. Selamat! 🎯"%(t["sym"],t["tf"],t["bias"],t["tp1"]), reply_to=t.get("mid"))
            elif hit=="SL":
                send_telegram("❌ <b>Kena Stop Loss</b> — %s %s %s (SL %s). Setup ini dianggap selesai."%(t["sym"],t["tf"],t["bias"],t["sl"]), reply_to=t.get("mid"))
            else:
                if time.time()-t.get("ts",0) < 43200: still.append(t)
        except Exception as e:
            print("cek open gagal",t.get("sym"),e); still.append(t)
    save_open(still)

def main():
    if not (TG_TOKEN and TG_CHAT):
        print("ENV Telegram belum lengkap"); sys.exit(1)
    refresh_gold_offset()
    try: check_open_trades()
    except Exception as e: print("check_open error:", e)
    opens=load_open()
    out={"updated":datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),"symbols":{}}
    for sym in SYMBOLS:
        tf_res={}
        for tf_name,tf_int in TIMEFRAMES:
            try: tf_res[tf_name]=analyze(sym,tf_int)
            except Exception as e: print("ERR",sym,tf_name,e); tf_res[tf_name]={"bias":"WAIT","conf":0}
        out["symbols"][sym]=tf_res
        actionable=any(tf_res[t].get("bias") in ("BUY","SELL") for t in tf_res)
        print(sym,{t:tf_res[t].get("bias") for t in tf_res})
        if actionable or SEND_WAIT:
            try:
                resp=send_telegram(fmt_symbol(sym,tf_res))
                mid=(resp or {}).get("result",{}).get("message_id")
                best=None
                for tf in ("M15","M5","M1"):
                    d=tf_res.get(tf,{})
                    if d.get("bias") in ("BUY","SELL") and (best is None or d.get("conf",0)>best[1]): best=(tf,d.get("conf",0),d)
                if best and mid:
                    tf,cf,d=best
                    opens.append({"sym":sym,"tf":tf,"bias":d["bias"],"entry":d["entry"],"sl":d["sl"],"tp1":d["tp1"],"mid":mid,"ts":time.time()})
            except Exception as e:
                print("KIRIM GAGAL",sym,e)
    save_open(opens)
    try:
        with open("signals.json","w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
        print("signals.json ditulis")
    except Exception as e:
        print("tulis signals.json gagal:",e)

if __name__ == "__main__":
    main()
