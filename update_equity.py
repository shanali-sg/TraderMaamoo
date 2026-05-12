"""
TraderMaamoo — Equity Tracker
Reads daily journal from the bot, updates equity chart and history.
Triggered by GitHub Actions every evening.
"""

import json
import os
from datetime import datetime

import matplotlib.pyplot as plt

JOURNAL_DIR = "journal"
HISTORY_FILE = "equity_history.json"
CHART_FILE = "equity_chart.png"
STARTING_EQUITY = 458.00


def load_history():
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)


def get_latest_equity():
    """Read the most recent journal file for today's equity."""
    try:
        files = sorted([f for f in os.listdir(JOURNAL_DIR) if f.endswith('.json')])
        if not files:
            return None

        latest = files[-1]
        with open(f"{JOURNAL_DIR}/{latest}", 'r') as f:
            data = json.load(f)

        equity = data.get('equity')
        date_str = data.get('date', latest.replace('.json', ''))
        return date_str, equity
    except Exception:
        return None


def update_chart(history):
    if len(history) < 2:
        print("Not enough data for chart")
        return

    dates = [h['date'] for h in history]
    equities = [h['equity'] for h in history]

    plt.figure(figsize=(10, 5))
    plt.plot(dates, equities, '#22c55e', linewidth=2, marker='o', markersize=5)
    plt.title('TraderMaamoo — Equity Curve', fontsize=13, fontweight='bold')
    plt.ylabel('Equity ($)', fontsize=11)
    plt.xlabel('Date', fontsize=11)
    plt.grid(True, alpha=0.25)
    plt.xticks(rotation=45, ha='right')

    gain = ((equities[-1] - equities[0]) / equities[0]) * 100
    plt.text(0.02, 0.95, f'{gain:+.1f}%', transform=plt.gca().transAxes,
             fontsize=12, fontweight='bold', color='white',
             bbox=dict(boxstyle='round', facecolor='#22c55e', alpha=0.85))

    plt.tight_layout()
    plt.savefig(CHART_FILE, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"Chart saved: ${equities[-1]:.2f} ({gain:+.1f}%)")


def main():
    print("TraderMaamoo — Equity Tracker")

    result = get_latest_equity()
    if not result:
        print("No journal data found")
        return

    date_str, equity = result
    if equity is None:
        print("No equity value in journal")
        return

    history = load_history()

    if not history or history[-1]['date'] != date_str:
        history.append({'date': date_str, 'equity': round(equity, 2)})
        save_history(history)
        print(f"Added: {date_str} — ${equity:.2f}")

    update_chart(history)

    if history:
        start = history[0]['equity']
        current = history[-1]['equity']
        gain = ((current - start) / start) * 100
        print(f"History: {len(history)} days | ${start:.2f} → ${current:.2f} | {gain:+.1f}%")


if __name__ == "__main__":
    main()
