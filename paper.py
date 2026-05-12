"""
paper.py — Stage 2 Trend-Surfer Paper Trading
Validates the strategy against historical data before live deployment.
Loads universe from symbols.txt if available, falls back to fixed list.

Configuration: 4 bullets | +4R target | 7-day time exit | No stop-loss
Entry: Red candle close near SMA20 — no green confirmation needed

Usage: python paper.py
Output: journal/paper_trades.json, journal/paper_trades.csv
"""

import json
import os
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import yfinance as yf
from dataclasses import dataclass, asdict
import warnings
warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

PAPER_START = "2026-04-01"
PAPER_END   = "2026-05-11"
DATA_START  = "2025-06-01"

STARTING_CAPITAL = 458.00
NUM_BULLETS = 4
BULLET_SIZE = STARTING_CAPITAL / NUM_BULLETS
RISK_PER_TRADE = 0.02

MIN_VOLUME = 200_000
RR_TARGET = 5.0
SMA_TOLERANCE = 0.03
SMA_SLOPE_MIN = 0.001
MIN_STOP_DISTANCE = 0.01
MAX_HOLD_DAYS = 7

SYMBOLS_FILE = "symbols.txt"
JOURNAL_JSON = "journal/paper_trades.json"
JOURNAL_CSV  = "journal/paper_trades.csv"

FALLBACK_SYMBOLS = [
    "NVDA","AVGO","MSFT","AAPL","AMZN","META","GOOGL","NFLX",
    "AMD","INTC","MU","QCOM","ADI","TXN","LRCX","AMAT",
    "MRVL","ON","STX","WDC","MCHP","MPWR","ENTG","TER",
    "CRM","ADBE","NOW","SNOW","PANW","CRWD","PLTR","DDOG",
    "NET","MDB","ZS","OKTA","DT","TEAM","HUBS","ORCL",
    "ANET","SMCI","COHR","TWLO",
    "CVX","XOM","SHEL","BP","TTE",
    "COP","EOG","DVN","OXY","FANG","CTRA","EQT",
    "SLB","HAL","BKR","KMI","WMB","TRGP","LNG","VLO","MPC",
    "APA","PSX","OVV","XLE","OIH","XOP","FCX",
    "JPM","BAC","WFC","C","GS","MS","AXP",
    "BLK","SCHW","KKR","BX","AIG","MET","PRU","TRV",
    "JNJ","PFE","MRK","ABBV","BMY","REGN","VRTX","BIIB","MRNA","ILMN",
    "WMT","TGT","COST","HD","LOW","NKE","SBUX","MCD","DIS","RCL",
    "SPY","QQQ","IWM","DIA","EEM","TLT",
    "GLD","SLV","DBC","USO","URA","CPER","WEAT","SOYB","UNG",
]


def load_symbols():
    if os.path.exists(SYMBOLS_FILE):
        with open(SYMBOLS_FILE, 'r') as f:
            symbols = [s.strip().upper() for s in f if s.strip()]
        if symbols:
            print(f"Loaded {len(symbols)} symbols from {SYMBOLS_FILE}")
            return symbols
    print(f"Using fallback universe: {len(FALLBACK_SYMBOLS)} symbols")
    return FALLBACK_SYMBOLS

SYMBOLS = load_symbols()


def fetch_data(symbol, start, end):
    try:
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 173: return None
        df.columns = ['open','high','low','close','volume']
        df.index = pd.to_datetime(df.index)
        df = df[df['volume'] > 0]
        return df if len(df) >= 173 else None
    except: return None

def calculate_indicators(df):
    df = df.copy()
    df['sma20'] = df['close'].rolling(20).mean()
    df['sma200'] = df['close'].rolling(200, min_periods=170).mean()
    df['avg_vol_20'] = df['volume'].rolling(20).mean()
    df['dist_sma20'] = abs(df['close'] - df['sma20']) / df['sma20']
    df['sma20_slope_3d'] = (df['sma20'] - df['sma20'].shift(3)) / df['sma20'].shift(3)
    return df


def detect_setup(df, idx, symbol, whitelist):
    """Red candle near SMA20 with quality filters — enter at the red candle's close."""
    if idx < 3: return None
    row = df.iloc[idx]; prev = df.iloc[idx-1]

    if pd.isna(row['sma20']) or pd.isna(row['sma200']): return None
    if row['sma20'] <= row['sma200']: return None

    sma_slope = row['sma20_slope_3d']
    if pd.isna(sma_slope) or sma_slope <= SMA_SLOPE_MIN: return None

    if pd.isna(prev['dist_sma20']) or prev['dist_sma20'] > SMA_TOLERANCE: return None
    if pd.isna(prev['avg_vol_20']) or prev['avg_vol_20'] < MIN_VOLUME: return None

    # Must be a red candle
    if prev['close'] >= prev['open']: return None

    # ── Red candle quality filters ──

    # 1. Minimum body size ≥ 0.5% of price (no dojis)
    body_pct = (prev['open'] - prev['close']) / prev['open']
    if body_pct < 0.005:
        return None

    # 2. Close must be in the lower half of the candle's range
    #    (sellers in control — not a wick recovery)
    candle_range = prev['high'] - prev['low']
    if candle_range > 0:
        close_position = (prev['close'] - prev['low']) / candle_range
        if close_position > 0.5:
            return None

    # 3. Volume must be at least 80% of 20-day average
    #    (selling with conviction, not a quiet drift)
    if prev['volume'] < prev['avg_vol_20'] * 0.8:
        return None

    # Enter at the red candle's close
    entry = float(prev['close'])
    stop = float(prev['low'])
    if stop >= entry: return None
    if (entry - stop) / entry < MIN_STOP_DISTANCE: return None

    # Composite score
    slope_score = min(float(sma_slope)*4000, 40)
    proximity = float(prev['dist_sma20'])
    if proximity < 0.005: prox_score = 15
    elif proximity < 0.015: prox_score = 30
    elif proximity < 0.025: prox_score = 20
    else: prox_score = 10
    vol_surge = float(prev['volume'])/float(prev['avg_vol_20'])
    if vol_surge > 2.0: vol_score = 30
    elif vol_surge > 1.5: vol_score = 22
    elif vol_surge > 1.0: vol_score = 15
    else: vol_score = 5

    score = slope_score + prox_score + vol_score
    if symbol in whitelist: score += 5

    return {'entry': entry, 'stop': stop, 'score': round(score,1),
            'sma_slope': round(float(sma_slope),4),
            'sma20_proximity': round(proximity,3),
            'vol_surge': round(vol_surge,2)}


def size_position(bullet_value, entry, stop):
    risk_per_share = entry - stop
    shares = round((bullet_value * RISK_PER_TRADE) / risk_per_share, 6)
    risk_dollars = round(shares * risk_per_share, 2)
    return shares, risk_dollars, risk_per_share


def classify_sector(symbol):
    try:
        if os.path.exists("finviz_data.csv"):
            df = pd.read_csv("finviz_data.csv")
            row = df[df['Ticker'] == symbol]
            if not row.empty:
                sector = str(row.iloc[0].get('Sector', 'UNKNOWN'))
                if 'Technology' in sector or 'Semiconductor' in sector: return 'TECH'
                if 'Energy' in sector or 'Oil' in sector: return 'ENERGY'
                if 'Financial' in sector or 'Bank' in sector or 'Insurance' in sector: return 'FINANCIALS'
                if 'Healthcare' in sector or 'Biotech' in sector or 'Pharma' in sector: return 'HEALTHCARE'
                if 'Consumer' in sector or 'Retail' in sector or 'Discretionary' in sector: return 'CONSUMER'
                if 'ETF' in sector or 'Index' in sector: return 'ETF/MACRO'
                if 'Industrial' in sector or 'Manufacturing' in sector: return 'INDUSTRIALS'
                if 'Basic Material' in sector or 'Chemical' in sector or 'Mining' in sector: return 'BASIC_MATERIALS'
                if 'Real Estate' in sector: return 'REAL_ESTATE'
                if 'Utility' in sector: return 'UTILITIES'
                if 'Communication' in sector: return 'COMMUNICATION'
                return sector.upper()[:15]
    except Exception: pass
    return 'UNKNOWN'

@dataclass
class Trade:
    trade_id: int
    symbol: str
    sector: str
    bullet: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stop_loss: float
    target: float
    shares: float
    pnl: float
    r_multiple: float
    exit_reason: str
    score: float


class PaperEngine:
    def __init__(self, symbols=None):
        self.symbols = symbols if symbols else SYMBOLS
        labels = [chr(65 + i) for i in range(NUM_BULLETS)]
        self.bullets = {
            label: {'free': True, 'value': BULLET_SIZE, 'frozen_until': None}
            for label in labels
        }
        self.open_trades = []
        self.closed_trades = []
        self.daily_journals = []
        self.trade_counter = 0
        self.data_cache = {}
        self.whitelist = set()

    def load_data(self):
        print(f"Loading {len(self.symbols)} symbols | {PAPER_START} → {PAPER_END}\n")
        loaded, failed = 0, []
        for i, sym in enumerate(self.symbols):
            if (i+1) % 25 == 0: print(f"  {i+1}/{len(self.symbols)}...")
            df = fetch_data(sym, DATA_START, PAPER_END)
            if df is not None:
                self.data_cache[sym] = calculate_indicators(df); loaded += 1
            else: failed.append(sym)
        print(f"  Loaded: {loaded} | Failed: {failed}\n")

    def check_exits(self, trade_date):
        closed_today = []
        for t in self.open_trades[:]:
            sym = t['symbol']
            if sym not in self.data_cache: continue
            df = self.data_cache[sym]; bar = df[df.index <= trade_date].iloc[-1]

            exit_price = None; reason = None
            entry_dt = pd.Timestamp(t['entry_date'])
            days_held = (trade_date - entry_dt).days

            if days_held >= MAX_HOLD_DAYS:
                exit_price = float(bar['close'])
                reason = 'TIME_EXIT'
            elif bar['high'] >= t['target']:
                exit_price = t['target']; reason = 'TARGET'

            if exit_price:
                pnl = (exit_price - t['entry']) * t['shares']
                r = (exit_price - t['entry']) / (t['entry'] - t['stop_loss'])
                b = self.bullets[t['bullet']]
                b['value'] += pnl; b['free'] = True
                b['frozen_until'] = (trade_date + timedelta(days=1)).strftime('%Y-%m-%d')
                self.trade_counter += 1
                self.closed_trades.append(Trade(
                    trade_id=self.trade_counter, symbol=sym,
                    sector=classify_sector(sym), bullet=t['bullet'],
                    entry_date=t['entry_date'], exit_date=trade_date.strftime('%Y-%m-%d'),
                    entry_price=t['entry'], exit_price=round(exit_price,2),
                    stop_loss=t['stop_loss'], target=t['target'],
                    shares=t['shares'],
                    pnl=round(float(pnl),2), r_multiple=round(float(r),2),
                    exit_reason=reason, score=t.get('score',0)))
                self.open_trades.remove(t)
        return closed_today

    def find_entries(self, trade_date):
        candidates = []
        for sym in self.symbols:
            if sym not in self.data_cache: continue
            df = self.data_cache[sym]; df_s = df[df.index <= trade_date]
            if len(df_s) < 201: continue
            sig = detect_setup(df_s, len(df_s)-1, sym, self.whitelist)
            if sig is None: continue
            if any(t['symbol'] == sym for t in self.open_trades): continue
            candidates.append({'symbol': sym, 'entry': sig['entry'],
                               'stop': sig['stop'], 'score': sig['score']})
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates

    def run(self):
        print("=" * 65)
        print("STAGE 2 TREND-SURFER — PAPER TRADING")
        print(f"Universe: {len(self.symbols)} symbols")
        print(f"Capital: ${STARTING_CAPITAL} | Bullets: {NUM_BULLETS} × ${BULLET_SIZE:.2f}")
        print(f"Target: +{RR_TARGET}R | Exit: {MAX_HOLD_DAYS}d | Entry: Red candle close @ SMA20")
        print("=" * 65)
        self.load_data()

        trading_days = pd.date_range(PAPER_START, PAPER_END, freq='B')
        total_setups, total_missed = 0, 0

        for trade_date in trading_days:
            date_str = trade_date.strftime('%Y-%m-%d')

            for b in self.bullets.values():
                if b['frozen_until'] and date_str >= b['frozen_until']:
                    b['free'] = True; b['frozen_until'] = None

            for t in self.check_exits(trade_date):
                print(f"  EXIT  [{t.exit_reason:9s}] {t.symbol:5s} [{t.bullet}] "
                      f"${t.entry_price:.2f} → ${t.exit_price:.2f} | "
                      f"PnL: ${t.pnl:+.2f} | R: {t.r_multiple:+.2f}")

            candidates = self.find_entries(trade_date)
            setups_today = len(candidates); total_setups += setups_today
            free = [l for l, b in self.bullets.items() if b['free']]
            n_take = min(len(candidates), len(free))
            total_missed += len(candidates) - n_take

            for i in range(n_take):
                c = candidates[i]; bl = free[i]; b = self.bullets[bl]
                shares, risk_dollars, risk_ps = size_position(b['value'], c['entry'], c['stop'])
                if shares <= 0: continue

                target = c['entry'] + (risk_ps * RR_TARGET)

                self.open_trades.append({
                    'symbol': c['symbol'], 'entry': c['entry'],
                    'stop_loss': c['stop'],
                    'target': target, 'shares': shares,
                    'bullet': bl, 'entry_date': date_str, 'score': c['score']})
                b['free'] = False
                print(f"  ENTRY [{bl}] {c['symbol']:5s} ${c['entry']:.2f} "
                      f"Target: ${target:.2f} "
                      f"{shares:.4f} sh | Risk: ${risk_dollars:.2f} | Score: {c['score']:.0f}")

            if len(candidates) > n_take:
                missed = [c['symbol'] for c in candidates[n_take:n_take+3]]
                print(f"  MISSED {len(candidates)-n_take}: {', '.join(missed)}"
                      f"{'...' if len(candidates)-n_take > 3 else ''}")

            av = sum(b['value'] for b in self.bullets.values())
            for t in self.open_trades:
                if t['symbol'] in self.data_cache:
                    df_s = self.data_cache[t['symbol']][
                        self.data_cache[t['symbol']].index <= trade_date]
                    if len(df_s) > 0:
                        av += (df_s.iloc[-1]['close'] - t['entry']) * t['shares']

            self.daily_journals.append({
                'date': date_str, 'account_value': round(float(av), 2),
                'bullets': {label: {'free': b['free'], 'value': round(b['value'], 2)}
                            for label, b in self.bullets.items()},
                'setups': setups_today})

        if self.open_trades:
            print(f"\n  Force-closing {len(self.open_trades)} positions...")
            for t in self.open_trades:
                sym = t['symbol']
                fp = float(self.data_cache[sym].iloc[-1]['close']) if sym in self.data_cache else t['entry']
                pnl = (fp - t['entry']) * t['shares']
                r = (fp - t['entry']) / (t['entry'] - t['stop_loss']) if (t['entry']-t['stop_loss']) > 0 else 0
                self.trade_counter += 1
                self.closed_trades.append(Trade(
                    trade_id=self.trade_counter, symbol=sym, sector=classify_sector(sym),
                    bullet=t['bullet'], entry_date=t['entry_date'], exit_date=PAPER_END,
                    entry_price=t['entry'], exit_price=round(fp,2),
                    stop_loss=t['stop_loss'], target=t['target'],
                    shares=t['shares'],
                    pnl=round(float(pnl),2), r_multiple=round(float(r),2),
                    exit_reason='EOD_FORCE', score=t.get('score',0)))

        self.generate_report(total_setups, total_missed)

    def generate_report(self, total_setups, total_missed):
        df = pd.DataFrame([asdict(t) for t in self.closed_trades])
        if len(df) == 0: print("\nNo trades."); return

        wins = df[df['pnl'] > 0]; losses = df[df['pnl'] <= 0]
        win_rate = len(wins)/len(df)*100
        aw = wins['r_multiple'].mean() if len(wins)>0 else 0
        al = losses['r_multiple'].mean() if len(losses)>0 else 0
        expectancy = (win_rate/100*aw) + ((1-win_rate/100)*al)
        total_pnl = df['pnl'].sum()
        final_cap = STARTING_CAPITAL + total_pnl

        print(f"\n{'='*65}")
        print(f"RESULTS")
        print(f"{'='*65}")
        print(f"  Trades:     {len(df)} | Wins: {len(wins)} ({win_rate:.1f}%)")
        print(f"  Expectancy: {expectancy:+.3f}R | Avg R: {df['r_multiple'].mean():+.2f}")
        print(f"  Avg Win:    {aw:+.2f}R (${wins['pnl'].mean():+.2f})")
        print(f"  Avg Loss:   {al:+.2f}R (${losses['pnl'].mean():+.2f})")
        print(f"  P&L:        ${total_pnl:+.2f} | Final: ${final_cap:,.2f}")
        print(f"  Growth:     {(total_pnl/STARTING_CAPITAL)*100:+.1f}%")
        print(f"  Setups:     {total_setups} seen / {total_missed} missed")

        all_sectors = ['TECH','ENERGY','FINANCIALS','HEALTHCARE','CONSUMER','ETF/MACRO',
                       'INDUSTRIALS','BASIC_MATERIALS','REAL_ESTATE','UTILITIES',
                       'COMMUNICATION','UNKNOWN']
        for sec in all_sectors:
            sub = df[df['sector']==sec]
            if len(sub)>0:
                sw = sub[sub['pnl']>0]
                print(f"  {sec:<15s}: {len(sub):3d} trades | {len(sw)/len(sub)*100:.0f}% WR | "
                      f"${sub['pnl'].sum():+.2f} | {sub['r_multiple'].mean():+.2f}R")

        os.makedirs('journal', exist_ok=True)
        jd = {'strategy': 'Stage 2 Trend-Surfer (Red Candle SMA20 Close Entry)',
              'period': f'{PAPER_START} to {PAPER_END}',
              'starting_capital': STARTING_CAPITAL, 'num_bullets': NUM_BULLETS,
              'rr_target': RR_TARGET, 'max_hold_days': MAX_HOLD_DAYS,
              'metrics': {
                  'total_trades': int(len(df)), 'win_rate': round(float(win_rate),1),
                  'expectancy': round(float(expectancy),3), 'total_pnl': round(float(total_pnl),2),
                  'final_capital': round(float(final_cap),2)},
              'trades': [asdict(t) for t in self.closed_trades],
              'daily_journals': self.daily_journals}
        with open(JOURNAL_JSON, 'w') as f: json.dump(jd, f, indent=2, default=str)
        df.to_csv(JOURNAL_CSV, index=False)
        print(f"\n  Saved: {JOURNAL_JSON}")


if __name__ == "__main__":
    PaperEngine().run()
