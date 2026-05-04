import requests
import json
import matplotlib.pyplot as plt
from datetime import datetime
import os
import re

def get_latest_equity():
    """Fetch latest equity from Telegram channel"""
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        return None
    
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
    except Exception as e:
        print(f"❌ Failed to fetch Telegram: {e}")
        return None
    
    # Find latest equity message
    for update in reversed(data.get('result', [])):
        text = update.get('message', {}).get('text', '')
        if 'EQUITY:' in text or ('💰' in text and '$' in text):
            # Extract number from message like "$1,245.50" or "$458.32"
            match = re.search(r'\$([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))
    return None

def load_history():
    """Load existing equity history"""
    try:
        with open('equity_history.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_history(history):
    with open('equity_history.json', 'w') as f:
        json.dump(history, f, indent=2)

def update_chart(history):
    if len(history) < 2:
        print("⚠️ Not enough data points for chart")
        return
    
    dates = [h['date'] for h in history]
    equities = [h['equity'] for h in history]
    
    plt.figure(figsize=(10, 6))
    plt.plot(dates, equities, 'g-', linewidth=2, marker='o', markersize=6)
    plt.title('TraderMaamoo – Equity Growth', fontsize=14, fontweight='bold')
    plt.ylabel('Account Equity ($)', fontsize=12)
    plt.xlabel('Date', fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45, ha='right')
    
    # Calculate gain
    start = equities[0]
    end = equities[-1]
    gain = ((end - start) / start) * 100
    
    # Add gain text box
    props = dict(boxstyle='round', facecolor='green', alpha=0.7)
    plt.text(0.02, 0.95, f'Total Gain: {gain:+.1f}%', transform=plt.gca().transAxes,
             fontsize=12, bbox=props, color='white', fontweight='bold')
    
    # Add min/max annotations
    min_idx = equities.index(min(equities))
    max_idx = equities.index(max(equities))
    plt.annotate(f'Min: ${equities[min_idx]:.2f}', xy=(dates[min_idx], equities[min_idx]),
                 xytext=(5, -10), textcoords='offset points', fontsize=8, color='red')
    plt.annotate(f'Max: ${equities[max_idx]:.2f}', xy=(dates[max_idx], equities[max_idx]),
                 xytext=(5, 10), textcoords='offset points', fontsize=8, color='green')
    
    plt.tight_layout()
    plt.savefig('equity_chart.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"✅ Chart updated: ${end:.2f} (+{gain:.1f}%)")

def main():
    print(f"🔄 Updating equity tracker...")
    
    # Get latest equity from Telegram
    equity = get_latest_equity()
    if not equity:
        print("❌ No equity message found in Telegram")
        print("   Make sure your Lambda has sent at least one EQUITY message")
        return
    
    # Update history
    history = load_history()
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Don't add duplicate entries for same day
    if not history or history[-1]['date'] != today:
        history.append({'date': today, 'equity': equity})
        save_history(history)
        print(f"✅ Added equity: ${equity:.2f} for {today}")
    else:
        print(f"⚠️ Equity already recorded for {today}: ${equity:.2f}")
    
    # Update chart
    update_chart(history)
    
    print(f"\n📊 Total history: {len(history)} days")
    print(f"   Start: ${history[0]['equity']:.2f}")
    print(f"   Current: ${history[-1]['equity']:.2f}")

if __name__ == "__main__":
    main()
