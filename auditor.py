"""
auditor.py — Strategy Audit, Whitelist & Sector Weight Generator
Reads trade journals, produces performance metrics, symbol whitelist,
and sector performance weights for live.py scoring.

Usage:
  python auditor.py                        # reads journal/paper_trades.json
  python auditor.py --journal path.json    # reads a specific journal file
"""

import json
import os
import sys
from datetime import date
from typing import List, Dict, Set
import pandas as pd
import numpy as np

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

JOURNAL_FILE = "journal/paper_trades.json"
WHITELIST_FILE = "data/whitelist.json"
AUDIT_FILE = "data/audit_report.json"

EXPECTANCY_WARNING = 0.20
EXPECTANCY_DANGER = 0.10
WIN_RATE_WARNING = 35.0
MAX_DRAWDOWN_WARNING = 15.0

DEFAULT_STARTING_CAPITAL = 458.00


# ═══════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════

def load_journal(filepath: str) -> Dict:
    with open(filepath, 'r') as f:
        return json.load(f)

def load_existing_audit(filepath: str) -> List[Dict]:
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r') as f:
            content = f.read().strip()
            if not content: return []
            data = json.loads(content)
            return data if isinstance(data, list) else data.get('reports', [])
    except (json.JSONDecodeError, FileNotFoundError):
        if os.path.exists(filepath):
            os.rename(filepath, filepath + '.corrupted')
        return []


# ═══════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════

def calculate_metrics(trades: List[Dict], journal: Dict = None) -> Dict:
    if not trades: return {'error': 'No trades to analyze'}

    capital = DEFAULT_STARTING_CAPITAL
    if journal:
        capital = float(journal.get('starting_capital', DEFAULT_STARTING_CAPITAL))

    df = pd.DataFrame(trades)
    total = len(df)
    wins = df[df['pnl'] > 0]; losses = df[df['pnl'] <= 0]
    wc, lc = len(wins), len(losses)
    wr = wc / total * 100 if total > 0 else 0

    total_pnl = float(df['pnl'].sum())
    aw = float(wins['pnl'].mean()) if wc > 0 else 0.0
    al = float(losses['pnl'].mean()) if lc > 0 else 0.0
    pf = abs(float(wins['pnl'].sum()) / float(losses['pnl'].sum())) if lc > 0 and losses['pnl'].sum() != 0 else float('inf')

    avg_r = float(df['r_multiple'].mean())
    awr = float(wins['r_multiple'].mean()) if wc > 0 else 0.0
    alr = float(losses['r_multiple'].mean()) if lc > 0 else 0.0
    expectancy = (wr/100 * awr) + ((1-wr/100) * alr)

    df['win'] = df['pnl'] > 0
    df['sid'] = (df['win'] != df['win'].shift()).cumsum()
    streaks = df.groupby(['win','sid']).size()
    mws = int(streaks[True].max()) if True in streaks.index.get_level_values(0) else 0
    mls = int(streaks[False].max()) if False in streaks.index.get_level_values(0) else 0

    df_s = df.sort_values('exit_date')
    df_s['cum_pnl'] = df_s['pnl'].cumsum()
    df_s['equity'] = capital + df_s['cum_pnl']

    if journal and 'entries' in journal:
        for entry in journal.get('entries', []):
            unrealized = entry.get('unrealized_pnl', 0)
            if unrealized != 0:
                journal_date = journal.get('date', date.today().isoformat())
                synthetic = pd.DataFrame([{
                    'exit_date': journal_date, 'pnl': unrealized}])
                df_s = pd.concat([df_s, synthetic], ignore_index=True)

    df_s['peak'] = df_s['equity'].cummax()
    df_s['dd'] = (df_s['equity'] - df_s['peak']) / df_s['peak'] * 100
    max_dd = float(df_s['dd'].min())

    recovery_factor = round(abs(total_pnl / max_dd), 2) if max_dd != 0 and total_pnl > 0 else 0.0

    exits = {str(k): int(v) for k, v in df['exit_reason'].value_counts().items()}

    stop_gaps = len(df[df['exit_reason'] == 'STOP_GAP'])
    stop_gap_pct = round(stop_gaps / total * 100, 1) if total > 0 else 0.0

    avg_hold_days = None
    if 'entry_date' in df.columns and 'exit_date' in df.columns:
        try:
            entry_dates = pd.to_datetime(df['entry_date'])
            exit_dates = pd.to_datetime(df['exit_date'])
            hold_days = (exit_dates - entry_dates).dt.days
            avg_hold_days = round(float(hold_days.mean()), 1)
        except Exception:
            pass

    sectors = {}
    if 'sector' in df.columns:
        for sec in df['sector'].unique():
            sub = df[df['sector'] == sec]; sw = sub[sub['pnl'] > 0]
            sectors[str(sec)] = {
                'trades': int(len(sub)),
                'pnl': round(float(sub['pnl'].sum()), 2),
                'win_rate': round(float(len(sw)/len(sub)*100), 1) if len(sub) > 0 else 0.0,
                'avg_r': round(float(sub['r_multiple'].mean()), 2)}

    dates = pd.to_datetime(df['entry_date'])
    period = f"{dates.min().strftime('%Y-%m-%d')} to {pd.to_datetime(df['exit_date']).max().strftime('%Y-%m-%d')}"

    return {
        'period': period,
        'starting_capital': capital,
        'total_trades': int(total), 'win_count': int(wc), 'loss_count': int(lc),
        'win_rate': round(float(wr), 1),
        'expectancy': round(float(expectancy), 3),
        'avg_r': round(float(avg_r), 2),
        'avg_win_r': round(float(awr), 2), 'avg_loss_r': round(float(alr), 2),
        'avg_win_dollar': round(float(aw), 2), 'avg_loss_dollar': round(float(al), 2),
        'profit_factor': round(float(pf), 2) if pf != float('inf') else 'infinite',
        'total_pnl': round(float(total_pnl), 2),
        'final_capital': round(float(capital + total_pnl), 2),
        'growth_pct': round(float((total_pnl/capital)*100), 1),
        'max_win_streak': int(mws), 'max_loss_streak': int(mls),
        'max_drawdown_pct': round(float(max_dd), 1),
        'recovery_factor': recovery_factor,
        'stop_gap_pct': stop_gap_pct,
        'avg_hold_days': avg_hold_days,
        'exit_reasons': exits, 'sectors': sectors}


# ═══════════════════════════════════════════════════════════════
# WHITELIST (ADAPTIVE CRITERIA)
# ═══════════════════════════════════════════════════════════════

def generate_whitelist(trades: List[Dict]) -> List[Dict]:
    df = pd.DataFrame(trades)
    total = len(df)

    min_trades = max(2, int(total / 20))
    min_avg_r = 0.20 if total < 50 else 0.30
    min_winrate = 35.0 if total < 50 else 40.0

    stats = df.groupby('symbol').agg(
        trades=('pnl','count'), wins=('pnl', lambda x: (x>0).sum()),
        total_pnl=('pnl','sum'), avg_r=('r_multiple','mean'),
        best_r=('r_multiple','max'), worst_r=('r_multiple','min'),
        last_traded=('exit_date','max')).reset_index()
    stats['win_rate'] = round(stats['wins']/stats['trades']*100, 1)

    stats['composite'] = round(stats['avg_r'] * np.sqrt(stats['trades']), 2)

    qualified = stats[(stats['trades'] >= min_trades) &
                      (stats['avg_r'] >= min_avg_r) &
                      (stats['win_rate'] >= min_winrate)]
    qualified = qualified.sort_values('composite', ascending=False)

    whitelist = []
    for _, r in qualified.iterrows():
        whitelist.append({
            'symbol': str(r['symbol']), 'trades': int(r['trades']),
            'win_rate': float(r['win_rate']), 'avg_r': round(float(r['avg_r']),2),
            'composite': round(float(r['composite']), 2),
            'total_pnl': round(float(r['total_pnl']),2),
            'best_r': round(float(r['best_r']),2),
            'worst_r': round(float(r['worst_r']),2),
            'last_traded': str(r['last_traded']),
            'added': date.today().isoformat()})
    return whitelist


# ═══════════════════════════════════════════════════════════════
# GATE CHECK
# ═══════════════════════════════════════════════════════════════

def check_gates(metrics: Dict) -> Dict:
    gates = {
        'expectancy_healthy': {
            'value': metrics['expectancy'], 'threshold': EXPECTANCY_WARNING,
            'status': 'PASS' if metrics['expectancy'] >= EXPECTANCY_WARNING else 'WARN'},
        'expectancy_critical': {
            'value': metrics['expectancy'], 'threshold': EXPECTANCY_DANGER,
            'status': 'PASS' if metrics['expectancy'] >= EXPECTANCY_DANGER else 'FAIL',
            'action': 'REDUCE: 1 bullet, 1% risk' if metrics['expectancy'] < EXPECTANCY_DANGER else None},
        'win_rate': {
            'value': metrics['win_rate'], 'threshold': WIN_RATE_WARNING,
            'status': 'PASS' if metrics['win_rate'] >= WIN_RATE_WARNING else 'WARN'},
        'drawdown': {
            'value': abs(metrics['max_drawdown_pct']), 'threshold': MAX_DRAWDOWN_WARNING,
            'status': 'PASS' if abs(metrics['max_drawdown_pct']) <= MAX_DRAWDOWN_WARNING else 'WARN'}}
    any_fail = any(g['status'] == 'FAIL' for g in gates.values())
    gates['overall'] = 'ALL_CLEAR' if not any_fail else 'ACTION_REQUIRED'
    return gates


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def run_audit(journal_path: str = JOURNAL_FILE):
    print(f"\n{'='*60}")
    print(f"AUDITOR — Strategy Audit & Whitelist")
    print(f"Date: {date.today().isoformat()}")
    print(f"{'='*60}")

    print(f"\n[1] Loading: {journal_path}")
    journal = load_journal(journal_path)
    trades = journal.get('trades', [])
    if not trades:
        print("  ERROR: No trades found."); return
    print(f"  {len(trades)} trades loaded")

    print(f"\n[2] Calculating metrics...")
    metrics = calculate_metrics(trades, journal)

    print(f"\n  {'─'*50}")
    print(f"  PERFORMANCE")
    print(f"  {'─'*50}")
    print(f"  Period:        {metrics['period']}")
    print(f"  Capital:       ${metrics['starting_capital']:,.2f}")
    print(f"  Trades:        {metrics['total_trades']} ({metrics['win_count']}W/{metrics['loss_count']}L)")
    print(f"  Win Rate:      {metrics['win_rate']}%")
    print(f"  Expectancy:    {metrics['expectancy']:+.3f}R")
    print(f"  Avg Win:       {metrics['avg_win_r']:+.2f}R (${metrics['avg_win_dollar']:+.2f})")
    print(f"  Avg Loss:      {metrics['avg_loss_r']:+.2f}R (${metrics['avg_loss_dollar']:+.2f})")
    print(f"  Profit Factor: {metrics['profit_factor']}")
    print(f"  Total P&L:     ${metrics['total_pnl']:+.2f}")
    print(f"  Final Capital: ${metrics['final_capital']:,.2f}")
    print(f"  Growth:        {metrics['growth_pct']}%")
    print(f"  Max Win Run:   {metrics['max_win_streak']}")
    print(f"  Max Loss Run:  {metrics['max_loss_streak']}")
    print(f"  Max Drawdown:  {metrics['max_drawdown_pct']}%")
    print(f"  Recovery:      {metrics['recovery_factor']}")
    if metrics['avg_hold_days'] is not None:
        print(f"  Avg Hold:      {metrics['avg_hold_days']} days")
    print(f"  Stop-Gap Rate: {metrics['stop_gap_pct']}%")
    print(f"  Exits:         {metrics['exit_reasons']}")

    eod_count = metrics['exit_reasons'].get('EOD_FORCE', 0)
    eod_pct = eod_count / metrics['total_trades'] * 100 if metrics['total_trades'] > 0 else 0
    if eod_pct > 20:
        print(f"  ⚠ {eod_pct:.0f}% EOD_FORCE exits — real performance may be slightly lower than shown")

    if metrics['sectors']:
        print(f"\n  SECTORS")
        for sec, sm in sorted(metrics['sectors'].items()):
            print(f"  {sec:<15s}: {sm['trades']:3d} | {sm['win_rate']:5.1f}% WR | "
                  f"${sm['pnl']:>+8.2f} | {sm['avg_r']:>+5.2f}R")

    print(f"\n[3] Gate check...")
    gates = check_gates(metrics)
    for name, g in gates.items():
        if name == 'overall': continue
        icon = 'PASS' if g['status']=='PASS' else 'WARN' if g['status']=='WARN' else 'FAIL'
        print(f"  [{icon}] {name}: {g['value']} (threshold: {g['threshold']})")
        if g.get('action'): print(f"       → {g['action']}")
    print(f"  Overall: {gates['overall']}")

    print(f"\n[4] Whitelist...")
    whitelist = generate_whitelist(trades)
    total_trades = len(trades)
    min_t = max(2, int(total_trades / 20))
    min_r = 0.20 if total_trades < 50 else 0.30
    min_w = 35.0 if total_trades < 50 else 40.0
    if whitelist:
        print(f"  Criteria: ≥{min_t} trades, ≥{min_r}R avg, ≥{min_w}% WR (adaptive)")
        print(f"  {len(whitelist)} symbols qualified:")
        print(f"  {'Sym':<6s} {'Trades':>6s} {'Win%':>7s} {'AvgR':>7s} {'Comp':>7s} {'PnL':>9s}")
        print(f"  {'─'*45}")
        for w in whitelist:
            print(f"  {w['symbol']:<6s} {w['trades']:6d} {w['win_rate']:6.1f}% "
                  f"{w['avg_r']:+6.2f}R {w['composite']:+7.2f} ${w['total_pnl']:+8.2f}")
    else:
        print("  No symbols qualified yet.")

    # Sector weights for live.py scoring
    sector_weights = {}
    for sec, sm in metrics['sectors'].items():
        trades_s = sm['trades']
        avg_r = sm['avg_r']
        if trades_s >= 2 and avg_r > 0.20:
            weight = round(avg_r * np.sqrt(trades_s), 2)
            sector_weights[sec] = weight

    if sector_weights:
        print(f"\n  SECTOR WEIGHTS (for live.py scoring)")
        for sec, w in sorted(sector_weights.items(), key=lambda x: x[1], reverse=True):
            print(f"  {sec:<15s}: +{w:.2f}")

    print(f"\n[5] Saving...")
    os.makedirs('data', exist_ok=True)

    wd = {'updated': date.today().isoformat(), 'generated_from': journal_path,
          'criteria': {'min_trades': min_t, 'min_avg_r': min_r, 'min_win_rate': min_w},
          'whitelist': whitelist,
          'sector_weights': sector_weights}
    with open(WHITELIST_FILE, 'w') as f:
        json.dump(wd, f, indent=2)
    print(f"  {WHITELIST_FILE} ({len(whitelist)} symbols, {len(sector_weights)} sectors)")

    existing = load_existing_audit(AUDIT_FILE)
    existing.append({
        'generated': date.today().isoformat(), 'journal_source': journal_path,
        'metrics': metrics, 'gates': gates, 'whitelist_count': len(whitelist),
        'qualification': {
            'min_20_trades': bool(metrics['total_trades'] >= 20),
            'expectancy_above_020': bool(metrics['expectancy'] >= 0.20),
            'win_rate_above_35': bool(metrics['win_rate'] >= 35.0),
            'all_pass': bool(metrics['total_trades'] >= 20 and
                            metrics['expectancy'] >= 0.20 and
                            metrics['win_rate'] >= 35.0)}})

    with open(AUDIT_FILE, 'w') as f:
        json.dump({'reports': existing, 'last_updated': date.today().isoformat()}, f, indent=2)
    print(f"  {AUDIT_FILE} ({len(existing)} reports)")

    print(f"\n{'='*60}")
    print(f"AUDIT COMPLETE")
    print(f"  Expectancy: {metrics['expectancy']:+.3f}R | Gates: {gates['overall']}")
    print(f"  Whitelist: {len(whitelist)} symbols | Sector weights: {len(sector_weights)}")
    print(f"  Reports: {len(existing)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    jp = JOURNAL_FILE
    if len(sys.argv) > 2 and sys.argv[1] == '--journal':
        jp = sys.argv[2]
    run_audit(jp)
