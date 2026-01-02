def floor_to_timeframe(epoch_sec, minutes_tf):
    """Pure math: floor to bucket start (no datetime/tz)"""
    sec_per_bucket = minutes_tf * 60
    return (epoch_sec // sec_per_bucket) * sec_per_bucket

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
                live_time = int(live_time)
                print("LTP from WS:", live_price)
                print("Time from WS:", live_time)

                # ========== BUCKETING LOGIC ADDED ==========
                minutes_tf = live_data["timeframe_minutes"]
                candle_ts = floor_to_timeframe(live_time, minutes_tf)
                
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


                short_ma_series, medium_ma_series, long_ma_series = calculate_moving_averages(
                    live_data["prices"], sp, mp, lp
                )


                short_val = short_ma_series.iloc[-1] if hasattr(short_ma_series, "iloc") and len(short_ma_series) > 0 else None
                print("short val ", short_val)
                medium_val = medium_ma_series.iloc[-1] if hasattr(medium_ma_series, "iloc") and len(medium_ma_series) > 0 else None
                print("medium val ", medium_val)
                long_val = long_ma_series.iloc[-1] if hasattr(long_ma_series, "iloc") and len(long_ma_series) > 0 else None
                print("long val ", long_val)


                live_data["short_ma"] = float(short_val) if short_val is not None else None
                live_data["medium_ma"] = float(medium_val) if medium_val is not None else None
                live_data["long_ma"] = float(long_val) if long_val is not None else None
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
                    signal = detect_signal(live_data["prices"], short_ma_series, medium_ma_series, long_ma_series)
                    print("signal", signal)
                    print("trade type", trade_type)


                    if signal:
                        side = signal


                        if trade_type == "Options":
                            strike_price = round(live_data["live_price"]) - (round(live_data["live_price"]) % 50)
                            if option_type == "Put":
                                strike_price = round(live_data["live_price"]) + (50 - (round(live_data["live_price"]) % 50))


                            expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
                            base_ticker = ticker.split(":")[1].split("-")[0]
                            symbol_to_trade = (
                                f"NSE:{base_ticker}{expiry.strftime('%y%b').upper()}"
                                f"{strike_price}{option_type[0].upper()}E"
                            )
                            print("symbol_to_trade", symbol_to_trade)
                        else:
                            symbol_to_trade = ticker


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
