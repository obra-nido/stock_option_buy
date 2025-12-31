import streamlit as st
import pandas as pd
from fyers_apiv3 import fyersModel
from src.fyers_client import get_access_token, get_historical_data, subscribe_to_live_data, place_order
from src.trading_logic import calculate_moving_averages, detect_signal, check_stop_loss
import time
import datetime

st.set_page_config(layout="wide")
st.title("Fyers Trading Bot")

# Initialize session state variables
if 'client_id' not in st.session_state:
    st.session_state.client_id = "F436AH37O2-100"
if 'secret_key' not in st.session_state:
    st.session_state.secret_key = "9F241B61PS"
if 'redirect_uri' not in st.session_state:
    st.session_state.redirect_uri = "https://trade.fyers.in/api-login/redirect-uri/index.html"
if 'access_token' not in st.session_state:
    st.session_state.access_token = None
if 'fyers' not in st.session_state:
    st.session_state.fyers = None

# --- Authentication Section ---
if st.session_state.access_token is None:
    st.header("Authentication")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.session_state.client_id = st.text_input("Client ID", st.session_state.client_id)
    with col2:
        st.session_state.secret_key = st.text_input("Secret Key", st.session_state.secret_key, type="password")
    with col3:
        st.session_state.redirect_uri = st.text_input("Redirect URI", st.session_state.redirect_uri)

    session = fyersModel.SessionModel(
        client_id=st.session_state.client_id,
        secret_key=st.session_state.secret_key,
        redirect_uri=st.session_state.redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    auth_code_url = session.generate_authcode()
    with col4:
        st.markdown(f"<a href='{auth_code_url}' target='_blank'>Click here to generate auth code</a>", unsafe_allow_html=True)
    
    auth_code = st.text_input("Auth Code")

    if st.button("Generate Access Token"):
        if all([st.session_state.client_id, st.session_state.secret_key, st.session_state.redirect_uri, auth_code]):
            try:
                st.session_state.access_token = get_access_token(
                    st.session_state.client_id, st.session_state.secret_key, st.session_state.redirect_uri, auth_code
                )
                st.rerun()
            except Exception as e:
                st.error(f"Failed to generate access token: {e}")
        else:
            st.error("Please fill in all the fields.")
else:
    # --- Main Application Logic ---
    if st.session_state.fyers is None:
        st.session_state.fyers = fyersModel.FyersModel(
            client_id=st.session_state.client_id, token=st.session_state.access_token, log_path=""
        )
    
    st.success("Successfully authenticated!")
    st.header("Bot Configuration")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        ticker = st.text_input("Ticker", "NSE:SBIN-EQ")
        timeframe = st.selectbox("Timeframe", ["1", "5", "15", "60"])
        trade_type = st.selectbox("Trade Type", ["Equity", "Options"])

    with col2:
        short_ma = st.number_input("Short MA", 11)
        medium_ma = st.number_input("Medium MA", 23)
        option_type = st.selectbox("Option Type", ["Call", "Put"])
    with col3:
        long_ma = st.number_input("Long MA", 50)
        max_trades = st.number_input("Max Trades", 10)
    with col4:

        quantity = st.number_input("Quantity", 1)
        expiry_str = st.text_input("Expiry (YYYY-MM-DD)", datetime.date.today().strftime("%Y-MM-DD"))

    if 'executed_trades' not in st.session_state:
        st.session_state.executed_trades = []
    
    if 'open_positions' not in st.session_state:
        st.session_state.open_positions = {}
        
    prices_data = {'prices': []}

    def on_message(message, prices_data):
        live_price = message['ltp']
        prices_data['prices'].append(live_price)

        short_ma_series, medium_ma_series, long_ma_series = calculate_moving_averages(prices_data['prices'], short_ma, medium_ma, long_ma)
        
        for trade_symbol, trade_info in list(st.session_state.open_positions.items()):
            if check_stop_loss(live_price, long_ma_series, trade_info["side"]):
                place_order(st.session_state.fyers, trade_symbol, trade_info["qty"], "sell" if trade_info["side"] == "buy" else "buy", "market")
                st.write(f"Stop-loss triggered for {trade_symbol}")
                del st.session_state.open_positions[trade_symbol]

        if len(st.session_state.executed_trades) < max_trades:
            signal = detect_signal(prices_data['prices'], short_ma_series, medium_ma_series, long_ma_series)
            
            if signal:
                side = signal
                
                if trade_type == "Options":
                    strike_price = round(live_price) - (round(live_price) % 50)
                    if option_type == "Put":
                        strike_price = round(live_price) + (50 - (round(live_price) % 50))
                        
                    expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
                    base_ticker = ticker.split(":")[1].split("-")[0]
                    symbol_to_trade = f"NSE:{base_ticker}{expiry.strftime('%y%b').upper()}{strike_price}{option_type[0].upper()}E"
                else:
                    symbol_to_trade = ticker
                    
                response = place_order(st.session_state.fyers, symbol_to_trade, quantity, side, "market")
                
                if response.get("s") == "ok":
                    order_id = response["id"]
                    order_book = st.session_state.fyers.orderbook({"id": order_id})
                    fill_price = order_book["orderBook"][0]["tradedPrice"] if order_book.get("s") == "ok" else live_price

                    trade = {"ticker": symbol_to_trade, "buying_price": live_price, "executed_price": fill_price, "executed": "Yes"}
                    st.session_state.executed_trades.append(trade)
                    st.session_state.open_positions[symbol_to_trade] = {"qty": quantity, "side": side}
                    st.write(f"Order placed: {trade}")
                else:
                    st.write(f"Order placement failed: {response}")

    if st.button("Start Bot"):
        st.write("Bot started...")
        
        @st.cache_data
        def fetch_data(_fyers, ticker, timeframe):
            to_date = datetime.datetime.now()
            from_date = to_date - datetime.timedelta(days=100)
            range_from = int(from_date.timestamp())
            range_to = int(to_date.timestamp())
            return get_historical_data(_fyers, ticker, timeframe, range_from=range_from, range_to=range_to)

        historical_data = fetch_data(st.session_state.fyers, ticker, timeframe)

        if historical_data.get("s") == "ok":
            prices_data['prices'] = [candle[4] for candle in historical_data.get("candles", [])]
            access_token_for_ws = f"{st.session_state.client_id}:{st.session_state.access_token}"
            subscribe_to_live_data(access_token_for_ws, [ticker], lambda msg: on_message(msg, prices_data))
        else:
            st.error(f"Failed to fetch historical data: {historical_data.get('message', 'Unknown error')}")

    st.header("Executed Trades")
    st.table(pd.DataFrame(st.session_state.executed_trades))
