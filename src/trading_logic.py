import pandas as pd
import numpy as np

def calculate_moving_averages(prices, short_window, medium_window, long_window,extra_long_window):
    prices_series = pd.Series(prices)
    short_ma = prices_series.rolling(window=short_window).mean()
    medium_ma = prices_series.rolling(window=medium_window).mean()
    long_ma = prices_series.rolling(window=long_window).mean()
    extra_long_ma = prices_series.rolling(window=extra_long_window).mean()
    return short_ma, medium_ma, long_ma, extra_long_ma

def detect_signal(prices, short_ma, medium_ma, long_ma):
    latest_price = prices[-1]
    latest_short_ma = short_ma.iloc[-1]
    latest_medium_ma = medium_ma.iloc[-1]
    latest_long_ma = long_ma.iloc[-1]

    previous_short_ma = short_ma.iloc[-2]
    previous_medium_ma = medium_ma.iloc[-2]

    if (latest_price > latest_short_ma and
        latest_price > latest_medium_ma and
        latest_short_ma > latest_medium_ma and
        latest_medium_ma > latest_long_ma and
        previous_short_ma <= previous_medium_ma):
        return "buy"
    elif (latest_price < latest_short_ma and
          latest_price < latest_medium_ma and
          latest_short_ma < latest_medium_ma and
          latest_medium_ma < latest_long_ma and
          previous_short_ma >= previous_medium_ma):
        return "sell"
    else:
        return None

def check_stop_loss(current_price, long_ma, side):
    latest_long_ma = long_ma.iloc[-1]
    if side == "buy" and current_price <= latest_long_ma:
        return True
    elif side == "sell" and current_price >= latest_long_ma:
        return True
    else:
        return False
