"""
trace_setups.py — Quick single-symbol trace for current strategy
Shows last 5 days and checks current red candle SMA20 entry conditions.
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

# Change these as needed
SYMBOLS = ["CALY"]
START = "2025-09-01"
END = "2026-05-12"

MIN_VOLUME = 200_000
SMA_TOLERANCE = 0.03
SMA_SLOPE_MIN = 0.001
MIN_STOP_DISTANCE = 0.01
RR_TARGET = 5.0
MIN_BODY_PCT = 0.005
MAX_CLOSE_POSITION = 0.5
MIN_VOLUME_RATIO = 0.8

for sym in SYMBOLS:
    print(f"\n{'='*60}")
    print(f"SYMBOL: {sym}")
    print(f"{'='*60}")

    bars = dc.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=sym, timeframe=TimeFrame.Day,
        start=START, end=END, feed='iex', limit=250))

    sym_bars = []
    for item in bars:
        if isinstance(item, tuple) and len(item) == 2 and item[0] == 'data':
            sym_bars = item[1].get(sym, [])
            break

    if len(sym_bars) < 172:
        print(f"  Only {len(sym_bars)} bars")
        continue

    bar_dicts = [b.model_dump() if hasattr(b,'model_dump') else b for b in sym_bars]
    df = pd.DataFrame(bar_dicts)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.set_index('timestamp')

    df['sma20'] = df['close'].rolling(20).mean()
    df['sma200'] = df['close'].rolling(200, min_periods=170).mean()
    df['avg_vol_20'] = df['volume'].rolling(20).mean()
    df['dist_sma20'] = abs(df['close'] - df['sma20']) / df['sma20']
    df['sma20_slope_3d'] = (df['sma20'] - df['sma20'].shift(3)) / df['sma20'].shift(3)

    # Last 5 bars
    print(f"\n  Last 5 trading days:")
    print(f"  {'Date':<12s} {'Open':>8s} {'Close':>8s} {'Low':>8s} {'SMA20':>8s} {'Dist%':>7s} {'Slope':>8s} {'Vol':>10s} {'Red':>5s}")
    print(f"  {'─'*85}")

    for i in range(-5, 0):
        row = df.iloc[i]
        date_str = df.index[i].strftime('%Y-%m-%d')
        is_red = "Yes" if row['close'] < row['open'] else "No"
        print(f"  {date_str:<12s} ${row['open']:>7.2f} ${row['close']:>7.2f} ${row['low']:>7.2f} "
              f"${row['sma20']:>7.2f} {row['dist_sma20']:>6.2%} "
              f"{row['sma20_slope_3d']:>8.4f} {row['volume']:>10,.0f} {is_red:>5s}")

    # Check current setup (red candle = prev bar)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    stage2 = not pd.isna(last['sma20']) and not pd.isna(last['sma200']) and last['sma20'] > last['sma200']
    rising = not pd.isna(last['sma20_slope_3d']) and last['sma20_slope_3d'] > SMA_SLOPE_MIN
    near = not pd.isna(prev['dist_sma20']) and prev['dist_sma20'] <= SMA_TOLERANCE
    red = prev['close'] < prev['open']
    body_pct = (prev['open'] - prev['close']) / prev['open'] if red else 0
    body_ok = body_pct >= MIN_BODY_PCT
    candle_range = prev['high'] - prev['low']
    close_pos = (prev['close'] - prev['low']) / candle_range if candle_range > 0 else 1
    close_ok = close_pos <= MAX_CLOSE_POSITION
    vol_ok = not pd.isna(prev['avg_vol_20']) and prev['avg_vol_20'] >= MIN_VOLUME and prev['volume'] >= prev['avg_vol_20'] * MIN_VOLUME_RATIO

    entry = float(prev['close'])
    stop = float(prev['low'])
    stop_dist = (entry - stop) / entry if stop < entry else 0
    stop_ok = stop < entry and stop_dist >= MIN_STOP_DISTANCE

    print(f"\n  Current Setup (prev bar as red candle):")
    print(f"    Stage2: {stage2} | Rising: {rising} | Near SMA20: {near} ({prev['dist_sma20']:.2%})")
    print(f"    Red: {red} | Body: {body_pct:.2%} | ClosePos: {close_pos:.0%} | VolOK: {vol_ok}")
    print(f"    Entry=${entry:.2f} | Stop=${stop:.2f} | StopDist={stop_dist:.1%}")

    all_pass = all([stage2, rising, near, red, body_ok, close_ok, vol_ok, stop_ok])
    if all_pass:
        target = entry + (entry - stop) * RR_TARGET
        print(f"    ✅ SETUP | Entry=${entry:.2f} Target=${target:.2f} (+{RR_TARGET}R)")
    else:
        fails = []
        if not stage2: fails.append("Stage2")
        if not rising: fails.append("Rising")
        if not near: fails.append(f"NearSMA({prev['dist_sma20']:.2%})")
        if not red: fails.append("Red")
        if not body_ok: fails.append(f"Body({body_pct:.2%})")
        if not close_ok: fails.append(f"ClosePos({close_pos:.0%})")
        if not vol_ok: fails.append("Volume")
        if not stop_ok: fails.append(f"StopDist({stop_dist:.1%})")
        print(f"    ❌ NO SETUP — Missing: {', '.join(fails)}")

print(f"\n{'='*60}")
print("DONE")
print(f"{'='*60}")
