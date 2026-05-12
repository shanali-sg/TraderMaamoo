"""
protect_positions.py — One-time emergency protection for naked positions.
Run this NOW to place stop-losses on any open positions.
"""

import os
import time
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import StopLimitOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce

API_KEY = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")

tc = TradingClient(API_KEY, SECRET_KEY, paper=False)

# Get current positions
positions = tc.get_all_positions()

if not positions:
    print("No open positions. You're safe.")
else:
    print(f"Found {len(positions)} open position(s):")
    for p in positions:
        sym = p.symbol
        qty = float(p.qty)
        avg_entry = float(p.avg_entry_price)
        current_price = float(p.current_price)
        pnl_pct = (current_price - avg_entry) / avg_entry * 100
        
        print(f"  {sym}: {qty:.4f} sh @ ${avg_entry:.2f} | Current: ${current_price:.2f} | PnL: {pnl_pct:+.2f}%")
        
        # Cancel any existing orders for this symbol
        try:
            tc.cancel_orders(symbols=[sym])
            time.sleep(0.3)
        except:
            pass
        
        # Place stop-loss at 3% below entry (or current price, whichever is higher)
        stop_price = round(max(avg_entry * 0.97, current_price * 0.97), 2)
        limit_price = round(stop_price * 0.995, 2)
        
        # Place take-profit at 2:1 R:R from entry
        risk = avg_entry - stop_price
        target_price = round(avg_entry + risk * 2, 2)
        
        try:
            # Stop-limit
            stop = tc.submit_order(StopLimitOrderRequest(
                symbol=sym, qty=qty, side=OrderSide.SELL,
                type=OrderType.STOP_LIMIT,
                stop_price=stop_price,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY))
            print(f"    Stop: ${stop_price} (limit ${limit_price})")
            
            # Take-profit
            target = tc.submit_order(LimitOrderRequest(
                symbol=sym, qty=qty, side=OrderSide.SELL,
                type=OrderType.LIMIT, limit_price=target_price,
                time_in_force=TimeInForce.DAY))
            print(f"    Target: ${target_price}")
            
        except Exception as e:
            print(f"    ERROR placing orders: {e}")
    
    print("\nDone. Check your Alpaca dashboard to confirm orders are placed.")
