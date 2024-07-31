import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import mplfinance as mpf
from scipy.signal import argrelextrema
import matplotlib.pyplot as plt

# Connect to MetaTrader 5
if not mt5.initialize():
    print("initialize() failed")
    quit()

# Define account details
account = 83444227
password = "A@DgU3Ac"
server = "MetaQuotes-Demo"

# Log in to the account
if not mt5.login(account, password, server):
    print("login() failed")
    mt5.shutdown()
    quit()

gold_HD5 = pd.DataFrame(mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 1, 10000))
gold_HD5['time'] = pd.to_datetime(gold_HD5['time'], unit='s')


# Function to calculate indicators
def calculate_indicators(data, short_window=10, atr_period=14):
    # Calculate short moving average
    data['MA_S'] = data['close'].rolling(window=short_window, min_periods=1).mean()

    # Calculate ATR
    data['TR'] = np.maximum(data['high'] - data['low'],
                            np.maximum(abs(data['high'] - data['close'].shift(1)),
                                       abs(data['low'] - data['close'].shift(1))))
    data['ATR'] = data['TR'].rolling(window=atr_period).mean()

    return data


# Function to plot signals and prices
def plot_signals(data):
    add_plots = []

    add_plots.append(mpf.make_addplot(data[['MA_S']]))

    buy_signals = data['open'].mask(data['Signal'] <= 0, np.NaN)
    sell_signals = data['open'].mask(data['Signal'] >= 0, np.NaN)
    profitable_buy_signals = buy_signals.mask(data['Profitable'] != 1, np.NaN)
    profitable_sell_signals = sell_signals.mask(data['Profitable'] != 1, np.NaN)
    stop_losses_hit = data['StopLoss'].mask(data['StopLoss'].isna(), np.NaN)

    if not buy_signals.isnull().all():
        add_plots.append(mpf.make_addplot(buy_signals, type='scatter', marker='^', color='g', markersize=100))
    if not sell_signals.isnull().all():
        add_plots.append(mpf.make_addplot(sell_signals, type='scatter', marker='v', color='r', markersize=100))
    if not profitable_buy_signals.isnull().all():
        add_plots.append(
            mpf.make_addplot(profitable_buy_signals, type='scatter', marker='o', color='black', markersize=100))
    if not profitable_sell_signals.isnull().all():
        add_plots.append(
            mpf.make_addplot(profitable_sell_signals, type='scatter', marker='o', color='black', markersize=100))
    if not stop_losses_hit.isnull().all():
        add_plots.append(
            mpf.make_addplot(stop_losses_hit, type='scatter', marker='x', color='orange', markersize=100))

    mpf.plot(data, type='candle', style='yahoo', title='Candlestick Chart with Moving Average and Signals',
             addplot=add_plots)


def generate_MAt_signals(data, volatility_threshold=0.001):
    data['Signal'] = 0

    # Finding local minima and maxima in the subset
    local_minima = argrelextrema(data['MA_S'].values, np.less, order=1)[0]
    local_maxima = argrelextrema(data['MA_S'].values, np.greater, order=1)[0]

    # Buy condition: local minima and low volatility
    buy_condition = (data.index.isin(data.index[local_minima]) &
                     (data['ATR'] < volatility_threshold * data['close']))
    data.loc[buy_condition, 'Signal'] = 1

    # Sell condition: local maxima and low volatility
    sell_condition = (data.index.isin(data.index[local_maxima]) &
                      (data['ATR'] < volatility_threshold * data['close']))
    data.loc[sell_condition, 'Signal'] = -1

    # Shift the signals to the second bar following the local extrema
    data['Signal'] = data['Signal'].shift(2)

    last_extrema_index = None
    second_last_extrema_index = None

    for i in range(2, len(data)):
        if i - 2 in local_minima or i - 2 in local_maxima:
            if last_extrema_index is not None:
                second_last_extrema_index = last_extrema_index
            last_extrema_index = i - 2

        if data['Signal'].iloc[i] != 0 and last_extrema_index is not None and second_last_extrema_index is not None:
            row = data.index[i]
            open_price = data['close'].iloc[i - 1]
            ma_price = data['MA_S'].iloc[i - 1]
            distance_open_ma = abs(open_price - ma_price)

            last_extrema = data['MA_S'].iloc[last_extrema_index]
            second_last_extrema = data['MA_S'].iloc[second_last_extrema_index]
            distance_extrema = abs(last_extrema - second_last_extrema)

            if distance_open_ma >= distance_extrema:
                data.loc[row, 'Signal'] = 0

    data = data.iloc[9:].copy()

    return data


def simulate_trading(data, initial_capital=10000, leverage=100, risk=0.01):
    capital = initial_capital
    position = 0  # Positive for long, negative for short
    balance = []
    profitable_signals = 0
    total_signals = 0
    stop_loss = None
    open_price = None
    open_index = None
    data['Profitable'] = np.nan  # Column to indicate if the signal was profitable
    data['StopLoss'] = np.nan  # Column to store stop loss hit point

    for i in range(len(data)):

        buy_price = data['open'].iloc[i] + data['spread'].iloc[i] / (2 * 100)
        sell_price = data['open'].iloc[i] - data['spread'].iloc[i] / (2 * 100)

        if position > 0:
            profit_loss = position * (sell_price - open_price)
        elif position < 0:
            profit_loss = position * (buy_price - open_price)
        else:
            profit_loss = 0

        # Calculate balance for each iteration
        current_balance = capital + profit_loss

        balance.append(current_balance)

        if data['Signal'].iloc[i] == 1:
            if position < 0:
                capital += profit_loss
                position = 0
                if profit_loss > 0:
                    profitable_signals += 1
                    data.at[open_index, 'Profitable'] = 1
                else:
                    data.at[open_index, 'Profitable'] = 0
            if position == 0:
                # Open new long position
                open_price = data['open'].iloc[i] + data['spread'].iloc[i] / (2 * 100)
                position = (risk * capital * leverage) / open_price
                open_index = data.index[i]  # Track the index where the position was opened
            total_signals += 1

        elif data['Signal'].iloc[i] == -1:
            if position > 0:
                capital += profit_loss
                position = 0
                if profit_loss > 0:
                    profitable_signals += 1
                    data.at[open_index, 'Profitable'] = 1
                else:
                    data.at[open_index, 'Profitable'] = 0
            if position == 0:
                # Open new short position
                open_price = data['open'].iloc[i] - data['spread'].iloc[i] / (2 * 100)
                position = -(risk * capital * leverage) / open_price
                open_index = data.index[i]  # Track the index where the position was opened
            total_signals += 1

        # Update stop loss only if in a profitable position
        if profit_loss > 0 and i > 1:
            if position > 0:
                new_stop_loss = data['MA_S'].iloc[i - 2]
                if stop_loss is None or new_stop_loss > stop_loss:
                    stop_loss = new_stop_loss
            elif position < 0:
                new_stop_loss = data['MA_S'].iloc[i - 2]
                if stop_loss is None or new_stop_loss < stop_loss:
                    stop_loss = new_stop_loss

        # Check stop loss
        if stop_loss is not None:
            if position > 0 and data['low'].iloc[i] < stop_loss:
                profit_loss = position * (stop_loss - open_price)
                capital += profit_loss
                data.at[data.index[i], 'StopLoss'] = stop_loss  # Store the price at which stop loss was hit
                position = 0
                stop_loss = None
                if profit_loss > 0:
                    profitable_signals += 1
                    data.at[open_index, 'Profitable'] = 1
                else:
                    data.at[open_index, 'Profitable'] = 0
            elif position < 0 and data['high'].iloc[i] > stop_loss:
                profit_loss = position * (stop_loss - open_price)
                capital += profit_loss
                data.at[data.index[i], 'StopLoss'] = stop_loss  # Store the price at which stop loss was hit
                position = 0
                stop_loss = None
                if profit_loss > 0:
                    profitable_signals += 1
                    data.at[open_index, 'Profitable'] = 1
                else:
                    data.at[open_index, 'Profitable'] = 0

    plt.figure(figsize=(10, 6))
    plt.plot(balance, label='Balance Over Time')
    plt.title('Balance Over Time')
    plt.xlabel('Time')
    plt.ylabel('Balance')
    plt.legend()
    plt.show()

    print(f"Initial Capital: {initial_capital}")
    print(f"Final Capital: {capital}")
    print(f"Final Balance: {balance[-1]}")
    print(f"Total Signals: {total_signals}")
    print(f"Profitable Signals: {profitable_signals}")
    print(f"Profitability Rate: {profitable_signals / total_signals * 100:.2f}%")

    return data


# Main execution
gold_HD5 = calculate_indicators(gold_HD5)
gold_HD5 = gold_HD5.set_index('time')
gold_HD5 = generate_MAt_signals(gold_HD5)
gold_HD5 = simulate_trading(gold_HD5)
plot_signals(gold_HD5)