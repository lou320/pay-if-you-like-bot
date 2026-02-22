import os
import logging
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, Side

# --- CONFIGURATION (FILL THESE IN!) ---
PRIVATE_KEY = "YOUR_WALLET_PRIVATE_KEY_HERE" # Need MATIC + USDC on Polygon
API_KEY = "YOUR_POLYMARKET_API_KEY"
API_SECRET = "YOUR_POLYMARKET_API_SECRET"
API_PASSPHRASE = "YOUR_POLYMARKET_API_PASSPHRASE"

# TARGET MARKET (Example: "Will Trump win?")
# You need the "Condition ID" from the market URL or API
CONDITION_ID = "0x....." 

# STRATEGY
BUY_PRICE_LIMIT = 0.40  # Only buy "YES" if price is cheaper than $0.40
AMOUNT_USDC = 10        # Bet $10 per trade

def main():
    # Initialize Client (Polygon Network)
    host = "https://clob.polymarket.com"
    chain_id = 137 # Polygon Mainnet
    
    try:
        client = ClobClient(
            host, 
            key=PRIVATE_KEY, 
            chain_id=chain_id,
            creds=None # If you have API creds, pass object here
        )
        print("✅ Connected to Polymarket CLOB")
        
        # 1. Get Current Price (Orderbook)
        orderbook = client.get_order_book(CONDITION_ID)
        
        # Check "Asks" (Sellers) to see the cheapest price for "YES"
        # Note: This logic depends on whether YES or NO token is being targeted
        # Simplified logic:
        lowest_sell_price = float(orderbook.asks[0].price)
        print(f"📉 Current Lowest Price: ${lowest_sell_price}")
        
        # 2. Decision Logic
        if lowest_sell_price <= BUY_PRICE_LIMIT:
            print(f"💰 Opportunity! Price ${lowest_sell_price} is <= Limit ${BUY_PRICE_LIMIT}")
            print(f"🚀 Placing Buy Order for ${AMOUNT_USDC}...")
            
            # Place Order
            resp = client.create_and_post_order(
                OrderArgs(
                    price=lowest_sell_price,
                    size=AMOUNT_USDC / lowest_sell_price, # Convert $10 to number of shares
                    side=Side.BUY,
                    token_id=CONDITION_ID, # Or specific Token ID for YES/NO
                    order_type=OrderType.FOK # Fill or Kill (Buy all or nothing)
                )
            )
            print(f"✅ Order Sent: {resp}")
            
        else:
            print(f"✋ Price too high. Waiting...")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()