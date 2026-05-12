"""
finviz_screener.py — Daily symbol universe refresh
Fetches Stage 2 pullback candidates from Finviz.
Excludes stocks with earnings in the surrounding volatility window.
Run at 9:20 AM ET before live.py.

Usage: python finviz_screener.py
Output: symbols.txt, finviz_data.csv
"""

import warnings
warnings.filterwarnings('ignore', category=FutureWarning)

from finvizfinance.screener.overview import Overview

STAGE2_FILTERS = {
    'Country': 'USA',
    'IPO Date': 'More than a year ago',
    'Average Volume': 'Over 200K',
    'Price': 'Over $5',
    'Relative Volume': 'Over 1.5',
    '20-Day Simple Moving Average': 'SMA20 above SMA200',
    '200-Day Simple Moving Average': 'Price above SMA200',
}

EARNINGS_WINDOWS = [
    {'Earnings Date': 'Previous 5 Days'},
    {'Earnings Date': 'Next 5 Days'},
]


def get_tickers(filters_dict):
    s = Overview()
    s.set_filter(filters_dict=filters_dict)
    df = s.screener_view()
    if df is None or df.empty:
        return set()
    return set(df['Ticker'].str.upper().tolist())


def main():
    # Get Stage 2 candidates with full data
    print("Fetching Stage 2 candidates...")
    s = Overview()
    s.set_filter(filters_dict=STAGE2_FILTERS)
    df = s.screener_view()
    
    if df is not None and not df.empty:
        # Save full data for sector classification
        df.to_csv('finviz_data.csv', index=False)
        stage2 = set(df['Ticker'].str.upper().tolist())
        print(f"  {len(stage2)} Stage 2 stocks found")
        print(f"  Full data saved to finviz_data.csv")
    else:
        print("  No Stage 2 stocks found")
        return

    # Get Stage 2 + earnings windows
    print("Fetching earnings windows...")
    earnings = set()
    for window in EARNINGS_WINDOWS:
        filters = {**STAGE2_FILTERS, **window}
        label = list(window.values())[0]
        earn = get_tickers(filters)
        print(f"  {label}: {len(earn)} stocks")
        earnings.update(earn)

    # Subtract earnings stocks
    if earnings:
        clean = stage2 - earnings
        removed = stage2 & earnings
        if removed:
            print(f"  Excluded ({len(removed)}): {', '.join(sorted(removed))}")
    else:
        clean = stage2

    print(f"  Final: {len(clean)} symbols")

    if clean:
        with open('symbols.txt', 'w') as f:
            f.write('\n'.join(sorted(clean)))
        print(f"\nSaved {len(clean)} symbols to symbols.txt")
    else:
        with open('symbols.txt', 'w') as f:
            f.write('\n'.join(sorted(stage2)))
        print(f"Fallback: saved {len(stage2)} symbols")

if __name__ == "__main__":
    main()
