import streamlit as st
import pandas as pd
from fyers_apiv3 import fyersModel
from src.fyers_client import get_access_token, subscribe_to_live_data, place_order
from src.trading_logic import calculate_moving_averages, detect_signal, check_stop_loss
import datetime
import threading


# ================= MODULE-LEVEL GLOBALS FOR LIVE DATA =================
live_data_lock = threading.Lock()
live_data = {
    "live_price": None,
    "live_time":[],
    "prices": [],
    "short_ma": None,
    "medium_ma": None,
    "long_ma": None,
    "extra_long_ma":None,
    "short_period": 11,
    "medium_period": 23,
    "long_period": 50,
    "extra_long_period":89,
    "first_print_done": False,
}

current_candle_ts = None

def floor_to_timeframe(epoch_sec, minutes_tf):
    """Pure math: floor to bucket start (no datetime/tz)"""
    sec_per_bucket = minutes_tf * 60
    return (epoch_sec // sec_per_bucket) * sec_per_bucket


# Global open positions and trades for use in WS thread
open_positions_lock = threading.Lock()
open_positions_global = {}

executed_trades_lock = threading.Lock()
executed_trades_global = []

# Global fyers client for WS thread
fyers_client = None


# --------------- BASIC SETUP ---------------
st.set_page_config("Directional Trading Bot", layout="wide")
st.title("Directional Trading Bot")


# --- Auto-refresh counter (for soft periodic rerun) ---
if "refresh_tick" not in st.session_state:
    st.session_state.refresh_tick = 0
st.session_state.refresh_tick += 1


# --------------- SESSION STATE INIT ---------------
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

if 'executed_trades' not in st.session_state:
    st.session_state.executed_trades = []
if 'open_positions' not in st.session_state:
    st.session_state.open_positions = {}

if 'ws_started' not in st.session_state:
    st.session_state.ws_started = False

# sync session_state views from globals for display
with open_positions_lock:
    st.session_state.open_positions = dict(open_positions_global)
with executed_trades_lock:
    st.session_state.executed_trades = list(executed_trades_global)


# --------------- AUTH SECTION ---------------
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
        st.markdown(
            f"<a href='{auth_code_url}' target='_blank'>Click here to generate auth code</a>",
            unsafe_allow_html=True
        )

    auth_code = st.text_input("Auth Code")

    if st.button("Generate Access Token"):
        if all([st.session_state.client_id, st.session_state.secret_key, st.session_state.redirect_uri, auth_code]):
            try:
                st.session_state.access_token = get_access_token(
                    st.session_state.client_id,
                    st.session_state.secret_key,
                    st.session_state.redirect_uri,
                    auth_code
                )
                st.rerun()
            except Exception as e:
                st.error(f"Failed to generate access token: {e}")
        else:
            st.error("Please fill in all the fields.")


# --------------- MAIN APP ---------------
else:

    if st.session_state.fyers is None:
        st.session_state.fyers = fyersModel.FyersModel(
            client_id=st.session_state.client_id,
            token=st.session_state.access_token,
            log_path=""
        )
    # expose fyers client to WS thread
    fyers_client = st.session_state.fyers

    st.success("Successfully authenticated!")
    st.header("Bot Configuration")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        ticker = st.text_input("Ticker", "NSE:NIFTY50-INDEX")
        option_step = st.number_input("Strike Price Increments", 50)
        expiry_str = st.text_input(
            "Expiry (YYYY-MM-DD)",
            datetime.date.today().strftime("%Y-%m-%d"))

    with col2:
        short_ma_period = st.number_input("Short MA", 11)
        trade_type = st.selectbox("Trade Type", ["Options", "Equity"])
        max_trades = st.number_input("Max Trades", 10)
        
        
    with col3:
        medium_ma_period = st.number_input("Medium MA", 23)
        expiry_type = st.selectbox("Expiry Type", ["Weekly", "Monthly"])
        side = st.selectbox("Side", ["buy"])

    with col4:
        long_ma_period = st.number_input("Long MA", 50)
        quantity = st.number_input("Quantity", 65)
        
    with col5:
        extra_long_ma_period = st.number_input("Mean Reversion Long MA", 89)
        timeframe_options = {
            "1 minute": "1",
            "5 minutes": "5",
            "15 minutes": "15",
            "60 minutes": "60",
            "1 day": "D"
        }
        timeframe_display = st.selectbox("Timeframe", list(timeframe_options.keys()))
        timeframe = timeframe_options[timeframe_display]

        

    # push MA periods to global live_data so callback can read them
    with live_data_lock:
        live_data["short_period"] = int(short_ma_period)
        live_data["medium_period"] = int(medium_ma_period)
        live_data["long_period"] = int(long_ma_period)
        live_data["extra_long_period"] = int(extra_long_ma_period)


    # --------------- WEBSOCKET CALLBACK USING ONLY GLOBALS ---------------
    def on_message(msg: dict):
        global current_candle_ts
        
        """
        Runs in WebSocket thread. Uses only module-level globals; no st.session_state
        mutation inside the thread.
        """
        try:
            # ignore control messages (cn, ful, sub etc.)
            if msg.get("type") in ("cn", "ful", "sub"):
                return

            with live_data_lock:
                if not live_data["first_print_done"]:
                    print("WS first message in app.py:", msg)
                    live_data["first_print_done"] = True

                live_price = msg.get("ltp")
                live_time = msg.get("exch_feed_time")
                if live_price is None or live_time is None:
                    return

                live_price = float(live_price)
               
                # ========== BUCKETING LOGIC ADDED ==========
                minutes_tf = int(timeframe) ##live_data["timeframe_minutes"]
                print("minute_tf ",minutes_tf )
                candle_ts = floor_to_timeframe(live_time, minutes_tf)
                print("candle_ts ",candle_ts )
                print("current_candle_ts ",current_candle_ts )
                
                # New candle? Append PRIOR LTP as candle close

                if current_candle_ts is None or candle_ts > current_candle_ts:
                    print(f"New {minutes_tf}m candle: {candle_ts}")
                    if current_candle_ts is not None:
                        live_data["prices"].append(live_data["live_price"])
                        live_data["live_time"].append(current_candle_ts)
                        print(f"Appended candle close at {current_candle_ts}")
                    
                    current_candle_ts = candle_ts
                    # Trim
                    if len(live_data["prices"]) > 500:
                        live_data["prices"] = live_data["prices"][-500:]
                        live_data["live_time"] = live_data["live_time"][-500:]
                # ===========================================

                live_data["live_price"] = live_price

                sp = live_data["short_period"]
                mp = live_data["medium_period"]
                lp = live_data["long_period"]
                mr = live_data["extra_long_period"]

            
                short_ma_series, medium_ma_series, long_ma_series, extra_long_ma_series  = calculate_moving_averages(
                    live_data["prices"], sp, mp, lp, mr
                )

               # print(short_ma_series, medium_ma_series, long_ma_series, extra_long_ma_series)


                short_val = short_ma_series.iloc[-1] if hasattr(short_ma_series, "iloc") and len(short_ma_series) > 0 else None
                print("short val ", short_val)
                medium_val = medium_ma_series.iloc[-1] if hasattr(medium_ma_series, "iloc") and len(medium_ma_series) > 0 else None
                print("medium val ", medium_val)
                long_val = long_ma_series.iloc[-1] if hasattr(long_ma_series, "iloc") and len(long_ma_series) > 0 else None
                print("long val ", long_val)
                extra_long_val = extra_long_ma_series.iloc[-1] if hasattr(extra_long_ma_series, "iloc") and len(extra_long_ma_series) > 0 else None
                print("long val ", extra_long_val)
                

                live_data["short_ma"] = float(short_val) if short_val is not None else None
                live_data["medium_ma"] = float(medium_val) if medium_val is not None else None
                live_data["long_ma"] = float(long_val) if long_val is not None else None
                live_data["extra_long_ma"] = float(extra_long_val) if long_val is not None else None
                print(live_data)


            # ---------- trading logic preserved, but uses globals ----------
            # Stop-loss on open positions
            
            with open_positions_lock:
                print("open positions ", open_positions_global.items())
                for trade_symbol, trade_info in list(open_positions_global.items()):
                    if check_stop_loss(live_data["live_price"], long_ma_series, trade_info["side"]):
                        place_order(
                            fyers_client,
                            trade_symbol,
                            trade_info["qty"],
                            "sell" if trade_info["side"] == "buy" else "buy",
                            "market"
                        )
                        print(f"Stop-loss triggered for {trade_symbol}")
                        del open_positions_global[trade_symbol]
            

            # Entry logic
            with executed_trades_lock, open_positions_lock:
                if len(executed_trades_global) < max_trades:
                    signal = detect_signal(live_data["prices"], short_ma_series, medium_ma_series, long_ma_series,extra_long_ma_series)
                    print("signal", signal)
                    print("trade type", trade_type)


                if signal:
                     ##   side = signal
                        ticker_local = ticker
                        if ticker_local == "NSE:NIFTY50-INDEX":
                            ticker_local = "NSE:NIFTY-INDEX"
                        if ticker_local == "NSE:NIFTYBANK-INDEX":
                            ticker_local = "NSE:BANKNIFTY-INDEX"
                        if trade_type == "Options" and expiry_type == "Monthly":
                            strike_price = round(live_data["live_price"]) - (round(live_data["live_price"]) % option_step)
                            if signal == "sell" : 
                                option_type = "Put"
                            else : option_type = "Call"
                            if option_type == "Put":
                                strike_price = round(live_data["live_price"]) + (option_step - (round(live_data["live_price"]) % option_step))
                                
                            expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
                            base_ticker = ticker_local.split(":")[1].split("-")[0]
                            symbol_to_trade = (
                                f"NSE:{base_ticker}{expiry.strftime('%y%b').upper()}"
                                f"{strike_price}{option_type[0].upper()}E"
                            )
                            print("symbol_to_trade", symbol_to_trade)
                    
                        elif trade_type == "Options" and expiry_type == "Weekly":
                            strike_price = round(live_data["live_price"]) - (round(live_data["live_price"]) % option_step)
                            if signal == "sell" : 
                                option_type = "Put"
                            else : option_type = "Call"
                            if option_type == "Put":
                                strike_price = round(live_data["live_price"]) + (option_step - (round(live_data["live_price"]) % option_step))
                                
                            expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
                            month_str = str(expiry.month)  # "1" not "01"
                            year_2digit = expiry.strftime("%y")  # "26"
                            date_2digit = expiry.strftime("%d")
                            expiry1 = year_2digit+month_str+date_2digit
                            base_ticker = ticker_local.split(":")[1].split("-")[0]
                            symbol_to_trade = (
                                f"NSE:{base_ticker}{expiry1.upper()}"
                                f"{strike_price}{option_type[0].upper()}E"
                            )
                            print("symbol_to_trade", symbol_to_trade)
                        
                        else:
                            symbol_to_trade = ticker_local
                        print("symbol_to_trade ",symbol_to_trade)

                        response = place_order(
                            fyers_client,
                            symbol_to_trade,
                            quantity,
                            side,
                            "market"
                        )


                        if response.get("s") == "ok":
                            order_id = response["id"]
                            order_book = fyers_client.orderbook({"id": order_id})
                            print("order book", order_book)
                            fill_price = (
                                order_book["orderBook"][0]["tradedPrice"]
                                if order_book.get("s") == "ok"
                                else live_data["live_price"]
                            )


                            trade = {
                                "ticker": symbol_to_trade,
                                "buying_price": live_data["live_price"],
                                "executed_price": fill_price,
                                "executed": "Yes"
                            }
                            executed_trades_global.append(trade)
                            open_positions_global[symbol_to_trade] = {
                                "qty": quantity,
                                "side": side
                            }
                        else:
                            print(f"Order placement failed: {response}")

        except Exception as e:
            print("on_message error:", e)


    # --------------- HISTORICAL DATA ---------------
    def fetch_data(_fyers, _ticker, _timeframe):
        to_date = datetime.datetime.now().date()
        from_date = to_date - datetime.timedelta(days=100)

        data = {
            "symbol": _ticker,
            "resolution": _timeframe,
            "date_format": "1",
            "range_from": str(from_date),
            "range_to": str(to_date),
            "cont_flag": "1"
        }
        return _fyers.history(data=data)


    # --------------- START BOT BUTTON ---------------
    if st.button("Start Bot") and not st.session_state.ws_started:
        st.session_state.ws_started = True
        st.write("Bot started...")

        # seed close prices so MA has history
        historical_data = fetch_data(fyers_client, ticker, timeframe)
        if historical_data.get("s") == "ok":
            candles = historical_data.get("candles", [])
            close_prices = [c[4] for c in candles]
            live_time = [c[0] for c in candles]
           # close_prices = [val for val in close_prices1 for _ in range(5)]
            with live_data_lock:
                live_data["prices"] = close_prices[-500:]
                live_data["live_time"] = live_time[-500:]
        else:
            st.error(f"Failed to fetch historical data: {historical_data.get('message', 'Unknown error')}")

        # subscribe via existing helper in a background thread
        current_candle_ts = live_data["live_time"][-1]
        access_token_for_ws = f"{st.session_state.client_id}:{st.session_state.access_token}"
        threading.Thread(
            target=subscribe_to_live_data,
            args=(access_token_for_ws, [ticker], on_message),
            daemon=True,
        ).start()

    """
    # --------------- LIVE METRICS SECTION ---------------
    st.header("Live Data")
    col1_m, col2_m, col3_m, col4_m = st.columns(4)
    with live_data_lock:
        lp_val = live_data["live_price"]
        s_val = live_data["short_ma"]
        m_val = live_data["medium_ma"]
        l_val = live_data["long_ma"]
        print("lp_val ", lp_val, s_val, m_val, l_val)

    with col1_m:
        st.metric("Live Price", f"{lp_val:.2f}" if lp_val is not None else "Waiting...")
    with col2_m:
        st.metric("Short MA", f"{s_val:.2f}" if s_val is not None else "Waiting...")
    with col3_m:
        st.metric("Medium MA", f"{m_val:.2f}" if m_val is not None else "Waiting...")
    with col4_m:
        st.metric("Long MA", f"{l_val:.2f}" if l_val is not None else "Waiting...")


    # --------------- EXECUTED TRADES TABLE ---------------
    st.header("Executed Trades")
    if st.session_state.executed_trades:
        st.table(pd.DataFrame(st.session_state.executed_trades))
    else:
        st.write("No trades executed yet.")


    # --------------- SOFT AUTO-REFRESH ---------------
    # Rerun periodically so UI picks up new live_data values
    if st.session_state.refresh_tick % 10 == 0:
        st.rerun()
    """