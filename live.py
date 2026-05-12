"""
live.py — Stage 2 Trend-Surfer Live Execution
Runs daily at market open against Alpaca IEX data.
4 bullets | +5R target | 7-day time exit | No stop-loss
Entry: Quality red candle close @ SMA20

Usage:
  export APCA_API_KEY_ID="your_key"
  export APCA_API_SECRET_KEY="your_secret"
  python live.py

Cron (ET): 35 9 * * 1-5 cd /path/to/bot && .venv/bin/python live.py >> logs/cron.log 2>&1
"""

import os
import sys
import json
import time
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple
import pandas as pd
import numpy as np

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest)
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

PAPER_MODE = False

INITIAL_CAPITAL = 458.00
NUM_BULLETS = 4
RISK_PER_TRADE = 0.02

MIN_VOLUME = 200_000
RR_TARGET = 5.0
SMA_TOLERANCE = 0.03
SMA_SLOPE_MIN = 0.001
MIN_STOP_DISTANCE = 0.01
MIN_PRICE = 5.00

MAX_CANDIDATES = 20
WHITELIST_SCORE_BOOST = 5
LOOKBACK_DAYS = 250
MAX_HOLD_DAYS = 7
MIN_SCORE = 65

# Red candle quality filters
MIN_BODY_PCT = 0.005      # Minimum body size 0.5% — no dojis
MAX_CLOSE_POSITION = 0.5  # Close must be in lower half of range
MIN_VOLUME_RATIO = 0.8    # Volume must be at least 80% of average

SYMBOLS_FILE = "symbols.txt"
WHITELIST_FILE = "data/whitelist.json"
AUDIT_FILE = "data/audit_report.json"
JOURNAL_DIR = "journal"
LOG_FILE = "logs/live.log"

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

os.makedirs("logs", exist_ok=True)
os.makedirs(JOURNAL_DIR, exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("live")


# ═══════════════════════════════════════════════════════════════
# ALPACA CLIENTS
# ═══════════════════════════════════════════════════════════════

def get_clients():
    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")
    if not api_key or not secret_key:
        logger.error("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set"); sys.exit(1)
    dc = StockHistoricalDataClient(api_key, secret_key)
    tc = TradingClient(api_key, secret_key, paper=PAPER_MODE)
    try:
        account = tc.get_account()
        logger.info(f"Alpaca connected | Status: {account.status} | "
                    f"Equity: ${float(account.equity):,.2f} | "
                    f"Mode: {'PAPER' if PAPER_MODE else 'LIVE'}")
    except Exception as e:
        logger.error(f"Alpaca connection failed: {e}"); sys.exit(1)
    return dc, tc


# ═══════════════════════════════════════════════════════════════
# WARM START
# ═══════════════════════════════════════════════════════════════

def load_whitelist():
    try:
        with open(WHITELIST_FILE, 'r') as f:
            data = json.load(f)
        symbols = {w['symbol'] for w in data.get('whitelist', [])}
        if symbols: logger.info(f"Whitelist loaded: {len(symbols)} symbols")
        return symbols
    except FileNotFoundError:
        logger.info("No whitelist found")
        return set()

def load_sector_weights():
    try:
        with open(WHITELIST_FILE, 'r') as f:
            data = json.load(f)
        weights = data.get('sector_weights', {})
        if weights:
            logger.info(f"Sector weights loaded: {len(weights)} sectors")
        return weights
    except FileNotFoundError:
        return {}

def load_baseline():
    try:
        with open(AUDIT_FILE, 'r') as f:
            data = json.load(f)
        reports = data.get('reports', [])
        if reports:
            m = reports[-1]['metrics']
            logger.info(f"Baseline: {m['expectancy']:+.3f}R, {m['win_rate']}% WR")
            return m
    except: pass
    logger.info("No audit baseline found")
    return None

def load_trade_history():
    trades = []
    if not os.path.exists(JOURNAL_DIR): return trades
    for fn in sorted(os.listdir(JOURNAL_DIR)):
        if not fn.endswith('.json'): continue
        try:
            with open(os.path.join(JOURNAL_DIR, fn), 'r') as f:
                data = json.load(f)
                for t in data.get('trades', data.get('entries', [])):
                    if t.get('pnl') and t['pnl'] != 0: trades.append(t)
        except: continue
    return trades


# ═══════════════════════════════════════════════════════════════
# EQUITY
# ═══════════════════════════════════════════════════════════════

def get_current_equity(tc, trade_history):
    try:
        account = tc.get_account()
        equity = float(account.equity)
        cash = float(account.cash)
        logger.info(f"Equity: ${equity:,.2f} | Cash: ${cash:,.2f}")
        return equity
    except Exception:
        total_pnl = sum(t.get('pnl', 0) for t in trade_history if t.get('pnl'))
        return INITIAL_CAPITAL + total_pnl


# ═══════════════════════════════════════════════════════════════
# CORPORATE ACTIONS BLACKLIST
# ═══════════════════════════════════════════════════════════════

def generate_blacklist():
    today = date.today()
    blacklist = set()
    try:
        from alpaca.data.historical.corporate_actions import CorporateActionsClient
        from alpaca.data.requests import CorporateActionsRequest

        api_key = os.getenv("APCA_API_KEY_ID")
        secret_key = os.getenv("APCA_API_SECRET_KEY")
        client = CorporateActionsClient(api_key, secret_key)

        request = CorporateActionsRequest(
            start=today.isoformat(),
            end=today.isoformat(),
            limit=500,
        )
        actions = client.get_corporate_actions(request)

        for action in actions:
            syms = getattr(action, 'symbols', []) or []
            if not syms:
                s = getattr(action, 'symbol', None)
                if s: syms = [s]
            for sym in syms:
                blacklist.add(str(sym).upper())

        logger.info(f"Corporate actions today: {len(blacklist)} symbols excluded")
    except Exception as e:
        logger.warning(f"Corporate actions check failed: {e}")
    return blacklist


# ═══════════════════════════════════════════════════════════════
# POSITION MANAGEMENT — 7-DAY TIME EXIT
# ═══════════════════════════════════════════════════════════════

def manage_open_positions(tc):
    try:
        positions = tc.get_all_positions()
    except Exception:
        logger.warning("Could not fetch positions")
        return set()

    active_symbols = set()
    for p in positions:
        sym = p.symbol
        active_symbols.add(sym)
        qty = float(p.qty)
        avg_entry = float(p.avg_entry_price)

        try:
            orders = tc.get_orders(status='open', symbols=[sym])
            has_target = any(o.side == OrderSide.SELL and
                            o.type == OrderType.LIMIT
                            for o in orders)
        except Exception:
            has_target = False

        entry_date_str = None
        try:
            journal_files = sorted(os.listdir(JOURNAL_DIR))
            for fn in reversed(journal_files):
                if not fn.endswith('.json'): continue
                with open(os.path.join(JOURNAL_DIR, fn), 'r') as f:
                    data = json.load(f)
                    for entry in data.get('entries', []):
                        if entry.get('symbol') == sym:
                            entry_date_str = entry.get('entry_date') or fn.replace('.json', '')
                            break
                if entry_date_str:
                    break
        except Exception:
            pass

        should_exit = False
        days_held = 0
        if entry_date_str:
            try:
                entry_dt = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
                days_held = (date.today() - entry_dt).days
                if days_held >= MAX_HOLD_DAYS:
                    logger.info(f"  [{sym}] 7-day time exit triggered ({days_held} days)")
                    should_exit = True
            except Exception:
                pass

        if should_exit:
            try:
                tc.cancel_orders(symbols=[sym])
                time.sleep(0.5)
                tc.submit_order(MarketOrderRequest(
                    symbol=sym, qty=qty, side=OrderSide.SELL,
                    type=OrderType.MARKET, time_in_force=TimeInForce.DAY))
                logger.info(f"  [{sym}] Exited at market — 7-day time stop")
                active_symbols.discard(sym)

                send_telegram(
                    f"<b>⏰ TIME EXIT</b> — TraderMaamoo\n"
                    f"Symbol: <b>{sym}</b>\n"
                    f"Held: {days_held} days\n"
                    f"Entry: ${avg_entry:.2f}"
                )
            except Exception as e:
                logger.warning(f"  [{sym}] Time exit failed: {e}")
        elif not has_target:
            risk_ps = avg_entry * 0.02
            target_price = round(avg_entry + risk_ps * RR_TARGET, 2)
            try:
                tc.cancel_orders(symbols=[sym])
                time.sleep(0.5)
                tc.submit_order(LimitOrderRequest(
                    symbol=sym, qty=qty, side=OrderSide.SELL,
                    type=OrderType.LIMIT, limit_price=target_price,
                    time_in_force=TimeInForce.DAY))
                logger.info(f"  [{sym}] Take-profit placed: ${target_price:.2f}")
            except Exception as e:
                logger.warning(f"  [{sym}] Protection failed: {e}")

    return active_symbols

# ═══════════════════════════════════════════════════════════════
# SCREENER
# ═══════════════════════════════════════════════════════════════

def calculate_indicators(df):
    df = df.copy()
    df['sma20'] = df['close'].rolling(20).mean()
    df['sma200'] = df['close'].rolling(200, min_periods=170).mean()
    df['avg_vol_20'] = df['volume'].rolling(20).mean()
    df['dist_sma20'] = abs(df['close'] - df['sma20']) / df['sma20']
    df['sma20_slope_3d'] = (df['sma20'] - df['sma20'].shift(3)) / df['sma20'].shift(3)
    return df

def score_setup(df, idx, symbol, whitelist, sector=None, sector_weights=None):
    if idx < 3: return None
    row = df.iloc[idx]; prev = df.iloc[idx-1]

    if pd.isna(row['sma20']) or pd.isna(row['sma200']): return None
    if row['sma20'] <= row['sma200']: return None

    sl = row['sma20_slope_3d']
    if pd.isna(sl) or sl <= SMA_SLOPE_MIN: return None

    if pd.isna(prev['dist_sma20']) or prev['dist_sma20'] > SMA_TOLERANCE: return None
    if pd.isna(prev['avg_vol_20']) or prev['avg_vol_20'] < MIN_VOLUME: return None

    # Must be a red candle
    if prev['close'] >= prev['open']: return None

    # ── Red candle quality filters ──

    # 1. Minimum body size ≥ 0.5% (no dojis)
    body_pct = (prev['open'] - prev['close']) / prev['open']
    if body_pct < MIN_BODY_PCT:
        return None

    # 2. Close must be in the lower half of the candle's range
    candle_range = prev['high'] - prev['low']
    if candle_range > 0:
        close_position = (prev['close'] - prev['low']) / candle_range
        if close_position > MAX_CLOSE_POSITION:
            return None

    # 3. Volume must be at least 80% of 20-day average
    if prev['volume'] < prev['avg_vol_20'] * MIN_VOLUME_RATIO:
        return None

    # Entry at the red candle's close
    entry_est = float(prev['close']); stop_est = float(prev['low'])
    if stop_est >= entry_est: return None
    if (entry_est - stop_est) / entry_est < MIN_STOP_DISTANCE: return None

    # Composite score
    slope_sc = min(float(sl)*4000, 40)
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
    score = slope_sc + prox_sc + vol_sc
    if symbol in whitelist: score += WHITELIST_SCORE_BOOST
    if sector and sector_weights and sector in sector_weights:
        score += sector_weights[sector]
    return round(score, 1)

def run_screener(dc, blacklist, whitelist):
    if not os.path.exists(SYMBOLS_FILE):
        logger.error(f"{SYMBOLS_FILE} not found. Run finviz_screener.py first.")
        return []

    with open(SYMBOLS_FILE, 'r') as f:
        symbols = [s.strip().upper() for s in f if s.strip()]
    symbols = [s for s in symbols if s not in blacklist]
    logger.info(f"Screener: {len(symbols)} symbols from {SYMBOLS_FILE} (after blacklist)")

    sector_map = {}
    try:
        if os.path.exists("finviz_data.csv"):
            fdf = pd.read_csv("finviz_data.csv")
            for _, row in fdf.iterrows():
                sector_map[row['Ticker']] = str(row.get('Sector', 'UNKNOWN'))
    except Exception:
        pass

    sector_weights = load_sector_weights()

    end_d = date.today().isoformat()
    start_d = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    candidates = []

    total = len(symbols)
    for i, sym in enumerate(symbols):
        if (i + 1) % 50 == 0 or i == 0 or i == total - 1:
            logger.info(f"  Scoring {i+1}/{total}...")

        try:
            bars = dc.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=sym, timeframe=TimeFrame.Day,
                start=start_d, end=end_d, feed='iex', limit=LOOKBACK_DAYS))

            sym_bars = []
            for item in bars:
                if isinstance(item, tuple) and len(item) == 2 and item[0] == 'data':
                    sym_bars = item[1].get(sym, [])
                    break

            if len(sym_bars) < 172:
                continue

            bar_dicts = []
            for b in sym_bars:
                if hasattr(b, 'model_dump'):
                    bar_dicts.append(b.model_dump())
                elif hasattr(b, 'dict'):
                    bar_dicts.append(b.dict())
                else:
                    bar_dicts.append(b)

            df = pd.DataFrame(bar_dicts)
            if 'timestamp' not in df.columns or 'close' not in df.columns:
                continue

            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')

            if df['close'].iloc[-1] < MIN_PRICE:
                continue

            df = calculate_indicators(df)
            sector = sector_map.get(sym, 'UNKNOWN')
            score = score_setup(df, len(df)-1, sym, whitelist, sector, sector_weights)

            if score is not None and score >= MIN_SCORE:
                row = df.iloc[-1]; prev = df.iloc[-2]
                entry = float(prev['close'])
                stop_val = float(prev['low'])
                candidates.append({
                    'symbol': sym, 'score': score,
                    'entry': entry,
                    'stop': stop_val,
                    'sma_slope': round(float(row['sma20_slope_3d']), 4),
                })

            time.sleep(0.3)

        except Exception:
            continue

    candidates.sort(key=lambda x: x['score'], reverse=True)
    top = candidates[:MAX_CANDIDATES]
    logger.info(f"Screener: {len(candidates)} scored → top {len(top)} ranked")
    if top:
        preview = ", ".join(f"{c['symbol']}({c['score']:.0f})" for c in top[:5])
        logger.info(f"  Top 5: {preview}")
    return top


# ═══════════════════════════════════════════════════════════════
# ORDER EXECUTION — NO STOP-LOSS, TAKE-PROFIT ONLY
# ═══════════════════════════════════════════════════════════════

def execute_entry(tc, symbol, shares, entry_price, target_price, bullet_label):
    if target_price <= entry_price:
        logger.error(f"  [{bullet_label}] REJECTED {symbol}: target <= entry")
        return None

    qty = round(shares, 6)
    entry_id = None

    try:
        entry_resp = tc.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY,
            type=OrderType.MARKET, time_in_force=TimeInForce.DAY))
        entry_id = str(entry_resp.id)
        logger.info(f"  [{bullet_label}] ENTRY {symbol}: {qty} sh | order {entry_id}")

        filled = False
        filled_price = None
        for _ in range(90):
            time.sleep(0.5)
            try:
                status = tc.get_order_by_id(entry_id)
                if status.status == 'filled':
                    filled = True
                    filled_price = float(status.filled_avg_price)
                    logger.info(f"  [{bullet_label}] FILLED {symbol} @ ${filled_price:.2f}")
                    break
                elif status.status in ('canceled', 'expired', 'rejected'):
                    logger.warning(f"  [{bullet_label}] Entry {status.status}")
                    return None
            except Exception:
                continue

        if not filled or filled_price is None:
            logger.warning(f"  [{bullet_label}] {symbol}: Entry not filled — cancelling")
            try: tc.cancel_order_by_id(entry_id)
            except: pass
            return None

        for _ in range(10):
            time.sleep(0.5)
            try:
                status = tc.get_order_by_id(entry_id)
                if status.status == 'closed':
                    logger.info(f"  [{bullet_label}] Entry order closed — placing take-profit")
                    break
            except Exception:
                continue
        time.sleep(1.0)

        try:
            limit_resp = tc.submit_order(LimitOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL,
                type=OrderType.LIMIT, limit_price=round(target_price, 2),
                time_in_force=TimeInForce.DAY))
            limit_id = str(limit_resp.id)
        except Exception as e:
            logger.error(f"  [{bullet_label}] Target rejected: {e}")
            try: tc.submit_order(MarketOrderRequest(
                symbol=symbol, qty=qty, side=OrderSide.SELL,
                type=OrderType.MARKET, time_in_force=TimeInForce.DAY))
            except: pass
            return None

        logger.info(f"  [{bullet_label}] {symbol}: Filled @ ${filled_price:.2f} | "
                    f"Target ${target_price:.2f} | 7d exit")

        return {
            'entry_order_id': entry_id,
            'target_order_id': limit_id,
            'filled_price': filled_price,
        }

    except Exception as e:
        logger.error(f"  [{bullet_label}] EXECUTION FAILED for {symbol}: {e}")
        if entry_id:
            try: tc.cancel_order_by_id(entry_id)
            except: pass
        return None


# ═══════════════════════════════════════════════════════════════
# JOURNAL
# ═══════════════════════════════════════════════════════════════

def save_journal(date_str, entries, bullets, screener_stats, blacklist_count, equity):
    journal = {
        'date': date_str, 'strategy': 'Stage 2 Trend-Surfer',
        'mode': 'paper' if PAPER_MODE else 'live',
        'equity': round(equity, 2),
        'num_bullets': NUM_BULLETS,
        'rr_target': RR_TARGET,
        'entries': entries,
        'bullet_state': {l: {'value': round(b['value'], 2), 'free': b['free']}
                         for l, b in bullets.items()},
        'screener_stats': screener_stats,
        'blacklist_count': blacklist_count}
    with open(f"{JOURNAL_DIR}/{date_str}.json", 'w') as f:
        json.dump(journal, f, indent=2, default=str)
    logger.info(f"Journal saved: {JOURNAL_DIR}/{date_str}.json")


# ═══════════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════════

def send_telegram(message):
    """Send a message to the private Telegram channel."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }, timeout=10)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════


def main():
    logger.info("=" * 60)
    logger.info(f"STAGE 2 TREND-SURFER | {date.today().isoformat()} | "
                f"{'PAPER' if PAPER_MODE else 'LIVE'} | "
                f"{NUM_BULLETS} bullets | +{RR_TARGET}R | {MAX_HOLD_DAYS}d exit")
    logger.info("=" * 60)

    dc, tc = get_clients()
    whitelist = load_whitelist()
    sector_weights = load_sector_weights()
    baseline = load_baseline()
    trade_history = load_trade_history()
    paper_pnl = sum(t.get('pnl', 0) for t in trade_history if t.get('pnl'))
    logger.info(f"Context: {len(trade_history)} paper trades | Paper P&L: ${paper_pnl:+.2f}")

    equity = get_current_equity(tc, trade_history)
    bullet_size = equity / NUM_BULLETS
    logger.info(f"Bullet size: ${bullet_size:,.2f} | Risk per trade: ${bullet_size * RISK_PER_TRADE:.2f}")

    # [1/4] Manage open positions
    logger.info("\n[1/4] Managing open positions...")
    active = manage_open_positions(tc)
    if active:
        logger.info(f"  Active positions: {', '.join(sorted(active))}")

    # [2/4] Corporate actions
    logger.info("\n[2/4] Corporate actions...")
    blacklist = generate_blacklist()

    # [3/4] Screener
    logger.info("\n[3/4] Screener...")
    candidates = run_screener(dc, blacklist, whitelist)
    if not candidates:
        logger.info("No candidates. Exiting.")
        save_journal(date.today().isoformat(), [], {},
                     {'candidates': 0}, len(blacklist), equity)
        return

    confirmed = []
    for c in candidates:
        risk_ps = c['entry'] - c['stop']
        target = c['entry'] + risk_ps * RR_TARGET
        c['target'] = target
        confirmed.append(c)
        logger.info(f"  {c['symbol']}: Entry=${c['entry']:.2f} Stop=${c['stop']:.2f} "
                    f"Target=${target:.2f} Score={c['score']:.0f}")

    confirmed.sort(key=lambda x: x.get('sma_slope', 0), reverse=True)

    # [4/4] Execution
    logger.info(f"\n[4/4] Execution ({len(confirmed)} candidates)...")
    labels = [chr(65 + i) for i in range(NUM_BULLETS)]
    bullets = {label: {'free': True, 'value': bullet_size} for label in labels}

    for i, sym in enumerate(sorted(active) if active else []):
        if i < NUM_BULLETS:
            bullets[labels[i]]['free'] = False

    free = [l for l, b in bullets.items() if b['free']]
    logger.info(f"  Bullets: {len(free)} free of {NUM_BULLETS} "
                f"(${bullet_size:,.2f}) | Risk/trade: ${bullet_size*RISK_PER_TRADE:.2f}")

    entries_today = []
    for i, c in enumerate(confirmed):
        if i >= len(free): break
        bl = free[i]; b = bullets[bl]; sym = c['symbol']
        if sym in active:
            logger.info(f"  [{bl}] SKIP {sym}: already holding"); continue

        risk_ps = c['entry'] - c['stop']
        shares = round((b['value'] * RISK_PER_TRADE) / risk_ps, 6)
        risk_dollars = round(shares * risk_ps, 2)
        if shares <= 0:
            logger.warning(f"  [{bl}] SKIP {sym}: position size zero")
            continue

        order = execute_entry(tc, sym, shares, c['entry'], c['target'], bl)
        if order:
            b['free'] = False
            entries_today.append({
                'symbol': sym, 'bullet': bl, 'entry_price_target': c['entry'],
                'stop': c['stop'], 'target': c['target'], 'shares': shares,
                'risk_dollars': risk_dollars, 'score': c['score'],
                'sma_slope': c.get('sma_slope', 0),
                'whitelisted': sym in whitelist, 'orders': order,
                'entry_date': date.today().isoformat()})

            send_telegram(
                f"<b>🔔 ENTRY</b> — TraderMaamoo\n"
                f"Symbol: <b>{sym}</b>\n"
                f"Entry: ${c['entry']:.2f}\n"
                f"Target: ${c['target']:.2f} (+{RR_TARGET}R)\n"
                f"Risk: ${risk_dollars:.2f}\n"
                f"Score: {c['score']:.0f}\n"
                f"Exit: 7 days or target"
            )

    logger.info(f"\nJournal...")
    save_journal(date.today().isoformat(), entries_today, bullets,
                 {'candidates': len(candidates), 'executed': len(entries_today)},
                 len(blacklist), equity)

    logger.info(f"\n{'='*60}")
    logger.info(f"SESSION COMPLETE | {len(entries_today)} trades")
    for e in entries_today:
        logger.info(f"  [{e['bullet']}] {e['symbol']}: {e['shares']:.4f} sh | "
                    f"Target: ${e['target']:.2f} | Score: {e['score']:.0f}")
    if not entries_today and len(confirmed) > 0:
        logger.info(f"  ({len(confirmed)} signals confirmed but none executed)")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
