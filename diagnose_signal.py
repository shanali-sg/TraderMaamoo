"""
diagnose_signal.py — Trace strategy checks on symbols from symbols.txt
Handles Pydantic Bar objects from alpaca-py v2.
Updated: +5R target | Quality red candle filters | 172 bar min | 170 min_periods
"""

import os, sys
from datetime import date, datetime, timedelta
import pandas as pd
import numpy as np

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
if not API_KEY or not SECRET_KEY:
    print("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY"); sys.exit(1)

dc = StockHistoricalDataClient(API_KEY, SECRET_KEY)
today = date.today()

MIN_VOLUME = 200_000
SMA_TOLERANCE = 0.03
SMA_SLOPE_MIN = 0.001
MIN_STOP_DISTANCE = 0.01
MIN_PRICE = 5.00
RR_TARGET = 5.0

# Red candle quality filters
MIN_BODY_PCT = 0.005
MAX_CLOSE_POSITION = 0.5
MIN_VOLUME_RATIO = 0.8

try:
    with open('symbols.txt', 'r') as f:
        test_symbols = [line.strip().upper() for line in f if line.strip()]
    print(f"Loaded {len(test_symbols)} symbols from symbols.txt\n")
except FileNotFoundError:
    print("symbols.txt not found. Run finviz_screener.py first.")
    sys.exit(1)

start_d = (today - timedelta(days=250)).isoformat()
end_d = today.isoformat()

print(f"Signal Diagnostic — {today.isoformat()} ({today.strftime('%A')})")
print(f"Strategy: Quality red candle SMA20 close | +{RR_TARGET}R target | 7d exit")
print(f"Data: {start_d} → {end_d}\n")

signals_found = 0
rejected_quality = 0

for sym in test_symbols:
    print("=" * 60)
    print(f"SYMBOL: {sym}")
    print("=" * 60)

    try:
        bars = dc.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=sym, timeframe=TimeFrame.Day,
            start=start_d, end=end_d, feed='iex', limit=250))
    except Exception as e:
        print(f"  API ERROR: {e}")
        continue

    sym_bars = []
    for item in bars:
        if isinstance(item, tuple) and len(item) == 2 and item[0] == 'data':
            sym_bars = item[1].get(sym, [])
            break

    print(f"  Total bars: {len(sym_bars)}")
    if len(sym_bars) < 172:
        print(f"  ❌ NEED 172+ bars, got {len(sym_bars)}")
        continue

    bar_dicts = []
    for b in sym_bars:
        if hasattr(b, 'model_dump'):
            bar_dicts.append(b.model_dump())
        elif hasattr(b, 'dict'):
            bar_dicts.append(b.dict())
        else:
            bar_dicts.append({
                'timestamp': getattr(b, 'timestamp', None),
                'open': getattr(b, 'open', None),
                'high': getattr(b, 'high', None),
                'low': getattr(b, 'low', None),
                'close': getattr(b, 'close', None),
                'volume': getattr(b, 'volume', None),
            })

    df = pd.DataFrame(bar_dicts)

    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')

    required = ['open', 'high', 'low', 'close', 'volume']
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        print(f"  ❌ Missing columns: {missing_cols}")
        continue

    df['sma20'] = df['close'].rolling(20).mean()
    df['sma200'] = df['close'].rolling(200, min_periods=170).mean()
    df['avg_vol_20'] = df['volume'].rolling(20).mean()
    df['dist_sma20'] = abs(df['close'] - df['sma20']) / df['sma20']
    df['sma20_slope_3d'] = (df['sma20'] - df['sma20'].shift(3)) / df['sma20'].shift(3)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    entry = float(prev['close'])
    stop = float(prev['low'])
    stop_dist = (entry - stop) / entry if stop < entry else 0

    checks = []

    # 1. Stage 2
    stage2 = not pd.isna(last['sma20']) and not pd.isna(last['sma200']) and last['sma20'] > last['sma200']
    checks.append(("SMA20 > SMA200", stage2,
        f"SMA20=${last['sma20']:.2f} SMA200=${last['sma200']:.2f}" if not pd.isna(last['sma20']) else "NaN"))

    # 2. SMA20 rising
    slope = last['sma20_slope_3d']
    rising = not pd.isna(slope) and slope > SMA_SLOPE_MIN
    checks.append(("SMA20 rising", rising, f"{slope:.4f}" if not pd.isna(slope) else "NaN"))

    # 3. Near SMA20
    near = not pd.isna(prev['dist_sma20']) and prev['dist_sma20'] <= SMA_TOLERANCE
    checks.append(("Near SMA20 (≤3%)", near,
        f"{prev['dist_sma20']:.2%}" if not pd.isna(prev['dist_sma20']) else "NaN"))

    # 4. Red candle
    red_candle = prev['close'] < prev['open']
    checks.append(("Red candle", red_candle,
        f"Open=${prev['open']:.2f} Close=${prev['close']:.2f}"))

    # 5. Body size ≥ 0.5%
    body_pct = (prev['open'] - prev['close']) / prev['open'] if prev['close'] < prev['open'] else 0
    body_ok = body_pct >= MIN_BODY_PCT
    checks.append(("Body ≥ 0.5%", body_ok, f"{body_pct:.2%}"))

    # 6. Close in lower half
    candle_range = prev['high'] - prev['low']
    close_pos = (prev['close'] - prev['low']) / candle_range if candle_range > 0 else 1
    close_ok = close_pos <= MAX_CLOSE_POSITION
    checks.append(("Close in lower half", close_ok, f"{close_pos:.1%} of range"))

    # 7. Volume ≥ 80% avg
    vol_ratio = prev['volume'] / prev['avg_vol_20'] if prev['avg_vol_20'] > 0 else 0
    vol_ok = vol_ratio >= MIN_VOLUME_RATIO and not pd.isna(prev['avg_vol_20']) and prev['avg_vol_20'] >= MIN_VOLUME
    checks.append(("Volume ≥ 80% avg", vol_ok,
        f"{vol_ratio:.0%} ({prev['volume']:,.0f} vs {prev['avg_vol_20']:,.0f})" if not pd.isna(prev['avg_vol_20']) else "NaN"))

    # 8. Price
    price_ok = entry >= MIN_PRICE
    checks.append(("Price ≥ $5", price_ok, f"${entry:.2f}"))

    # 9. Stop distance
    stop_ok = stop_dist >= MIN_STOP_DISTANCE and stop < entry
    checks.append(("Stop dist ≥ 1%", stop_ok,
        f"{stop_dist:.2%} (entry=${entry:.2f} stop=${stop:.2f})"))

    passed = 0
    for name, result, detail in checks:
        icon = "✓" if result else "✗"
        print(f"  {icon} {name:<22s} | {detail}")
        if result: passed += 1

    print(f"  {'─'*50}")
    if passed == 9:
        prox = float(prev['dist_sma20'])
        if prox < 0.005: prox_sc = 15
        elif prox < 0.015: prox_sc = 30
        elif prox < 0.025: prox_sc = 20
        else: prox_sc = 10
        vs = float(prev['volume'])/float(prev['avg_vol_20'])
        if vs > 2.0: vol_sc = 30
        elif vs > 1.5: vol_sc = 22
        elif vs > 1.0: vol_sc = 15
        else: vol_sc = 5
        score = min(float(slope)*4000, 40) + prox_sc + vol_sc
        target = entry + (entry - stop) * RR_TARGET
        risk = entry - stop
        print(f"  ✅ SIGNAL | Score: {score:.0f}")
        print(f"     Entry=${entry:.2f} (red candle close)")
        print(f"     Stop=${stop:.2f} (red candle low)")
        print(f"     Target=${target:.2f} (+{RR_TARGET}R)")
        print(f"     Risk=${risk:.2f}/share | StopDist={stop_dist:.1%}")
        signals_found += 1
    else:
        fails = [name for name, result, _ in checks if not result]
        print(f"  ❌ {passed}/9 | Missing: {', '.join(fails)}")
        # Track quality filter rejections separately
        quality_fails = [name for name, result, _ in checks if not result and name in
                        ('Body ≥ 0.5%', 'Close in lower half', 'Volume ≥ 80% avg')]
        if quality_fails:
            rejected_quality += 1
    print()

print("=" * 60)
print(f"DONE — {signals_found} signal(s) found out of {len(test_symbols)} symbols")
if rejected_quality > 0:
    print(f"  ({rejected_quality} symbol(s) rejected by quality filters alone)")
print("=" * 60)
