import pandas as pd
from src.trading_logic import calculate_moving_averages, detect_signal, check_stop_loss

def test_calculate_moving_averages():
    prices = [10, 12, 15, 14, 16, 18, 20]
    short_window = 3
    medium_window = 4
    long_window = 5

    short_ma, medium_ma, long_ma = calculate_moving_averages(prices, short_window, medium_window, long_window)

    # Expected values calculated manually
    expected_short_ma = pd.Series([None, None, 12.333333, 13.666667, 15.0, 16.0, 18.0])
    expected_medium_ma = pd.Series([None, None, None, 12.75, 14.25, 15.75, 17.0])
    expected_long_ma = pd.Series([None, None, None, None, 13.4, 15.0, 16.6])

    pd.testing.assert_series_equal(short_ma, expected_short_ma, rtol=1e-5)
    pd.testing.assert_series_equal(medium_ma, expected_medium_ma, rtol=1e-5)
    pd.testing.assert_series_equal(long_ma, expected_long_ma, rtol=1e-5)

def test_detect_buy_signal():
    prices = [100, 102, 101, 103, 105]
    short_ma, medium_ma, long_ma = calculate_moving_averages(prices, 2, 3, 4)
    assert detect_signal(prices, short_ma, medium_ma, long_ma) == "buy"

def test_detect_sell_signal():
    prices = [105, 103, 104, 102, 100]
    short_ma, medium_ma, long_ma = calculate_moving_averages(prices, 2, 3, 4)
    assert detect_signal(prices, short_ma, medium_ma, long_ma) == "sell"

def test_check_stop_loss_buy():
    prices = [100, 102, 101, 103, 105]
    _, _, long_ma = calculate_moving_averages(prices, 2, 3, 4)
    assert check_stop_loss(95, long_ma, "buy") == True
    assert check_stop_loss(110, long_ma, "buy") == False

def test_check_stop_loss_sell():
    prices = [105, 103, 104, 102, 100]
    _, _, long_ma = calculate_moving_averages(prices, 2, 3, 4)
    assert check_stop_loss(110, long_ma, "sell") == True
    assert check_stop_loss(95, long_ma, "sell") == False
