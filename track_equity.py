import requests
import json
import matplotlib.pyplot as plt
from datetime import datetime
import os

def get_latest_equity():
    """Fetch latest equity from Telegram channel"""
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    response = requests.get(url)
    data = response.json()
    
    # Find latest equity message
    for update in reversed(data.get('result', [])):
        text = update.get('message', {}).get('text', '')
        if text.startswith('💰') or '$' in text:
            # Extract number from message like "$1,245.50"
            import re
            match = re.search(r'\$([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))
    return None

def load_history():
    """Load existing equity history"""
    try:
        with open('equity_history.json', 'r') as f:
            return json.load(f)
    except:
        return []

def save_history(history):
    with open('equity_history.json', 'w') as f:
        json.dump(history, f)

def update_chart(history):
    if not history:
        return
    
    dates = [h['date'] for h in history]
    equities = [h['equity'] for h in history]
    
    plt.figure(figsize=(10, 6))
    plt.plot(dates, equities, 'g-', linewidth=2, marker='o', markersize=4)
    plt.title('TraderMaamoo – Equity Growth')
    plt.ylabel('Account Equity ($)')
    plt.xlabel('Date')
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    
    # Calculate gain
    start = equities[0]
    end = equities[-1]
    gain = ((end - start) / start) * 100
    plt.text(0.02, 0.95, f'Total Gain: {gain:.1f}%', transform=plt.gca().transAxes, 
             fontsize=12, bbox=dict(facecolor='green', alpha=0.7))
    
    plt.tight_layout()
    plt.savefig('equity_chart.png', dpi=150)
    print(f"✅ Chart updated: ${end:.2f} (+{gain:.1f}%)")

def main():
    # Get latest equity from Telegram
    equity = get_latest_equity()
    if not equity:
        print("No equity message found in Telegram")
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
        print(f"Equity already recorded for {today}")
    
    # Update chart
    update_chart(history)

if __name__ == "__main__":
    main()
