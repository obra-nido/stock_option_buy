import streamlit as st
import pandas as pd
from fyers_apiv3 import fyersModel
from src.fyers_client import get_access_token, get_historical_data, subscribe_to_live_data, place_order
from src.trading_logic import calculate_moving_averages, detect_signal, check_stop_loss
import time
import datetime

st.title("Fyers Trading Bot")

client_id = st.text_input("Client ID")
secret_key = st.text_input("Secret Key", type="password")
redirect_uri = st.text_input("Redirect URI")

if 'access_token' not in st.session_state:
    st.session_state.access_token = None

if st.session_state.access_token is None:
    auth_code = st.text_input("Auth Code")
    if st.button("Generate Access Token"):
        if client_id and secret_key and redirect_uri and auth_code:
            st.session_state.access_token = get_access_token(client_id, secret_key, redirect_uri, auth_code)
            st.success("Access token generated successfully!")
        else:
            st.error("Please fill in all the fields.")
else:
    st.success("Access token is already generated.")

    fyers = fyersModel.FyersModel(client_id=client_id, token=st.session_state.access_token, log_path="fyers_log")

    ticker = st.text_input("Ticker", "NSE:SBIN-EQ")
    timeframe = st.selectbox("Timeframe", ["1", "5", "15", "60"])
    short_ma = st.number_input("Short MA", 11)
    medium_ma = st.number_input("Medium MA", 23)
    long_ma = st.number_input("Long MA", 50)
    max_trades = st.number_input("Max Trades", 10)
    trade_type = st.selectbox("Trade Type", ["Equity", "Options"])
    option_type = st.selectbox("Option Type", ["Call", "Put"])
    quantity = st.number_input("Quantity", 1)
    expiry_str = st.text_input("Expiry (YYYY-MM-DD)", "2024-12-31")

    if 'executed_trades' not in st.session_state:
        st.session_state.executed_trades = []
    
    if 'open_positions' not in st.session_state:
        st.session_state.open_positions = {}
        
    prices_data = {'prices': []}

    def on_message(message, prices_data):
        live_price = message['ltp']
        prices_data['prices'].append(live_price)

        short_ma_series, medium_ma_series, long_ma_series = calculate_moving_averages(prices_data['prices'], short_ma, medium_ma, long_ma)
        
        # Check for stop-loss
        for trade_symbol, trade_info in list(st.session_state.open_positions.items()):
            if check_stop_loss(live_price, long_ma_series, trade_info["side"]):
                place_order(fyers, trade_symbol, trade_info["qty"], "sell" if trade_info["side"] == "buy" else "buy", "market")
                st.write(f"Stop-loss triggered for {trade_symbol}")
                del st.session_state.open_positions[trade_symbol]

        # Check for new signals
        if len(st.session_state.executed_trades) < max_trades:
            signal = detect_signal(prices_data['prices'], short_ma_series, medium_ma_series, long_ma_series)
            
            if signal:
                order_type_to_place = "market"
                side = signal
                
                if trade_type == "Options":
                    strike_price = round(live_price / 50) * 50
                    expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
                    
                    if option_type == "Call":
                        symbol_to_trade = f"NSE:{ticker}{expiry.strftime('%y%b').upper()}{strike_price}CE"
                    else:
                        symbol_to_trade = f"NSE:{ticker}{expiry.strftime('%y%b').upper()}{strike_price}PE"
                else:
                    symbol_to_trade = ticker
                    
                response = place_order(fyers, symbol_to_trade, quantity, side, order_type_to_place)
                
                if response.get("s") == "ok":
                    order_id = response["id"]
                    order_book = fyers.orderbook({"id": order_id})
                    fill_price = order_book["orderBook"][0]["tradedPrice"] if order_book["s"] == "ok" else live_price

                    trade = {
                        "ticker": symbol_to_trade,
                        "buying_price": live_price,
                        "executed_price": fill_price,
                        "executed": "Yes"
                    }
                    st.session_state.executed_trades.append(trade)
                    st.session_state.open_positions[symbol_to_trade] = {"qty": quantity, "side": side}
                    st.write(f"Order placed: {trade}")
                else:
                    st.write(f"Order placement failed: {response}")

    if st.button("Start Bot"):
        st.write("Bot started...")
        
        @st.cache_data
        def fetch_data():
            to_date = datetime.datetime.now().date()
            from_date = to_date - datetime.timedelta(days=100) # Fetch enough data for MAs
            return get_historical_data(fyers, ticker, timeframe, range_from=str(from_date), range_to=str(to_date))

        historical_data = fetch_data()

        if historical_data["s"] == "ok":
            prices_data['prices'] = [candle[4] for candle in historical_data["candles"]]
            subscribe_to_live_data(f"{client_id}:{st.session_state.access_token}", [ticker], lambda msg: on_message(msg, prices_data))
        else:
            st.error(f"Failed to fetch historical data: {historical_data}")

    st.write("Executed Trades:")
    st.table(pd.DataFrame(st.session_state.executed_trades))
