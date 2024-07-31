import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import time
import numpy as np
import requests
import threading

# Connect to MetaTrader 5
if not mt5.initialize():
    print("initialize() failed")
    quit()

# Define account details
account = #acc number
password = #"password"
server = "MetaQuotes-Demo"

# Log in to the account
if not mt5.login(account, password, server):
    print("login() failed")
    mt5.shutdown()
    quit()

# Define global variables
symbol = "XAUUSD"
timeframe = mt5.TIMEFRAME_M5
gold_MD = pd.DataFrame()
now = None
hold1 = None
hold2 = None
last_extrema = None
scnd_last_extrema = None
hold_time = None
closed_orders = []  # List to keep track of closed orders

# Pushover API details
pushover_user_key = #noti user key
pushover_api_token = #noti api token


# Function to send a Pushover notification
def send_notification(title, message):
    url = "https://api.pushover.net/1/messages.json"
    data = {
        "token": pushover_api_token,
        "user": pushover_user_key,
        "title": title,
        "message": message
    }
    response = requests.post(url, data=data)
    if response.status_code != 200:
        send_notification('Error', f"Failed to send notification: {response.text}")


# Message to indicate algorithm has started
send_notification('Trading Algorithm', 'MA Extrema Algorithm Has Started')


# Function to calculate indicators (SameSgn)
def calculate_indicators(data):
    # Calculate short and long moving averages
    data['MA'] = data['close'].rolling(window=10, min_periods=1).mean()
    data['MA_price_diff'] = abs(data['close'] - data['MA'])

    return data


# Function to generate signals based on indicators
def generate_signals(data):
    global hold1, hold2, last_extrema, scnd_last_extrema

    # Check if the second to last value is a local minimum or maximum
    if data['MA'].iloc[-2] < data['MA'].iloc[-3] and data['MA'].iloc[-2] < data['MA'].iloc[-1]:
        scnd_last_extrema = last_extrema
        last_extrema = data['MA'].iloc[-2]
        if scnd_last_extrema is None:
            data.at[data.index[-1], 'Signal'] = 1
        else:
            distance_extrema = abs(last_extrema - scnd_last_extrema)
            if data['MA_price_diff'].iloc[-1] >= distance_extrema:
                data.at[data.index[-1], 'Signal'] = 0
            else:
                data.at[data.index[-1], 'Signal'] = 1
    elif data['MA'].iloc[-2] > data['MA'].iloc[-3] and data['MA'].iloc[-2] > data['MA'].iloc[-1]:
        scnd_last_extrema = last_extrema
        last_extrema = data['MA'].iloc[-2]
        if scnd_last_extrema is None:
            data.at[data.index[-1], 'Signal'] = -1
        else:
            distance_extrema = abs(last_extrema - scnd_last_extrema)
            if data['MA_price_diff'].iloc[-1] >= distance_extrema:
                data.at[data.index[-1], 'Signal'] = 0
            else:
                data.at[data.index[-1], 'Signal'] = -1
    else:
        data.at[data.index[-1], 'Signal'] = 0

    if hold1 is not None:
        data.at[data.index[-2], 'Signal'] = hold1
    else:
        data.at[data.index[-2], 'Signal'] = 0

    if hold2 is not None:
        data.at[data.index[-3], 'Signal'] = hold2
    else:
        data.at[data.index[-3], 'Signal'] = 0

    hold1 = data['Signal'].iloc[-1]
    hold2 = data['Signal'].iloc[-2]

    return data


# Function to get account balance
def get_account_balance():
    account_info = mt5.account_info()
    account_balance = account_info.balance
    return account_balance


# Function to calculate buy order size based on a percentage of account capital
def buy_order_size(risk=0.01):
    global account_balance
    if account_balance is not None:
        order_value = account_balance * risk
        tick = mt5.symbol_info_tick("XAUUSD")
        if tick is not None:
            current_price = tick.ask
            order_volume = order_value / current_price
            return float(np.floor(order_volume * 100) / 100)
        else:
            send_notification('Error', "Failed to retrieve current ask price for XAUUSD")
            return None
    else:
        return None


# Function to calculate sell order size based on a percentage of account capital
def sell_order_size(risk=0.01):
    global account_balance
    if account_balance is not None:
        order_value = account_balance * risk
        tick = mt5.symbol_info_tick("XAUUSD")
        if tick is not None:
            current_price = tick.bid
            order_volume = order_value / current_price
            return float(np.floor(order_volume * 100) / 100)
        else:
            send_notification('Error', "Failed to retrieve current bid price for XAUUSD")
            return None
    else:
        return None


# Function to place a market order
def place_mkt_order(action, volume):

    tick = mt5.symbol_info_tick("XAUUSD")
    price = tick.ask if action == 'BUY' else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "XAUUSD",
        "volume": volume,
        "price": price,
        "type": mt5.ORDER_TYPE_BUY if action == 'BUY' else mt5.ORDER_TYPE_SELL,
        "type_filling": mt5.ORDER_FILLING_IOC,  # immediate or cancel
    }

    # Place the order
    result = mt5.order_send(request)

    # Check if the order was successful
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        send_notification("Order Executed", f"Position {action} {volume} XAUUSD opened")

    else:
        send_notification("Order Failed", f"Failed to execute {action} order, retcode={result.retcode}")


# Function to close all open positions of a specified type
def close_all_open_positions(type):
    type_mapping = {
        'BUY': mt5.ORDER_TYPE_BUY,
        'SELL': mt5.ORDER_TYPE_SELL
    }

    order_type = type_mapping[type]

    for position in mt5.positions_get():
        if position.symbol == "XAUUSD" and position.type == order_type:
            mt5.Close(symbol=position.symbol)
            send_notification("Position Closed", f"Closed previous {type} position")


def sl_change(ticket, new_sl):
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl": new_sl,
    }

    # Send the request to modify the stop loss
    result = mt5.order_send(request)

    # Check if the modification was successful
    if not result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"Failed to modify stop loss for position {ticket}, retcode={result.retcode}")
        send_notification('Error', f"Failed to modify stop loss for position {ticket}, retcode={result.retcode}")


def round_down_3dp(value):
    return np.floor(value * 1000) / 1000.0


def round_up_3dp(value):
    return np.ceil(value * 1000) / 1000.0


# Function to check closed orders for stop losses triggered
def check_closed_orders():
    global closed_orders

    while True:
        recent_orders = mt5.history_orders_get(datetime.now(), datetime.now() + timedelta(hours=3))

        # Find new closed orders not in closed_orders
        if recent_orders is not None:
            new_closed_orders = [order for order in recent_orders if
                             order not in closed_orders and order.reason == mt5.ORDER_REASON_SL]

        # Process new orders
            for order in new_closed_orders:
                closed_orders.append(order)
                order_type = "Buy" if order.type == mt5.ORDER_TYPE_BUY else "Sell"
                send_notification("Stop Loss Triggered",
                                  f"{order_type} order {order.position_id} stopped out at {order.price_current}")

        # Remove orders from closed_orders that are no longer in current_closed_orders
        closed_orders = [order for order in closed_orders if order in recent_orders]

        time.sleep(1)


# Function to get current market data and trade
def main():
    global now, gold_MD, account_balance, hold_time

    # Start closed orders check thread
    closed_orders_thread = threading.Thread(target=check_closed_orders)
    closed_orders_thread.daemon = True
    closed_orders_thread.start()

    invalid_data_count = 0
    market_closed_notified = False

    try:
        while True:
            # Loop until valid data is collected
            while True:
                # Get the last 2 completed bars, excluding the current bar
                gold_MD = pd.DataFrame(mt5.copy_rates_from_pos(symbol, timeframe, 1, 12))
                gold_MD['time'] = pd.to_datetime(gold_MD['time'], unit='s')

                if hold_time is not None:
                    # Calculate minute difference
                    minute_diff = (gold_MD['time'].iloc[-1].minute - hold_time.minute) % 60

                    # Check if the minute difference is 5
                    if minute_diff == 5:
                        hold_time = gold_MD['time'].iloc[-1]
                        invalid_data_count = 0
                        if market_closed_notified:
                            send_notification("Market Status", "Market has reopened.")
                            market_closed_notified = False
                        break  # Valid data collected, exit the loop

                    invalid_data_count += 1

                    if invalid_data_count >= 5:
                        if not market_closed_notified:
                            send_notification("Market Status", "Market has closed.")
                            market_closed_notified = True

                        # Check if the data time has changed from the previous one
                        if gold_MD['time'].iloc[-1] != hold_time:
                            hold_time = gold_MD['time'].iloc[-1]
                            send_notification("Market Status", "Market has reopened.")
                            market_closed_notified = False
                            invalid_data_count = 0  # Reset counter on valid data
                            break  # Exit the loop with the next piece of data

                    time.sleep(1)  # Wait for 1 second before retrying
                else:
                    hold_time = gold_MD['time'].iloc[-1]
                    break

            if not gold_MD.empty:
                gold_MD = calculate_indicators(gold_MD)
                gold_MD = generate_signals(gold_MD)

                if gold_MD['Signal'].iloc[-1] > 0:
                    close_all_open_positions('SELL')

                    account_balance = get_account_balance()
                    buy_order_size_value = buy_order_size()
                    if buy_order_size_value is not None:
                        print(f"Placing Buy Order, Size: {buy_order_size_value}")
                        place_mkt_order('BUY', buy_order_size_value)
                    else:
                        print("Unable to retrieve account capital or ask price")

                elif gold_MD['Signal'].iloc[-1] < 0:
                    close_all_open_positions('BUY')

                    account_balance = get_account_balance()
                    sell_order_size_value = sell_order_size()
                    if sell_order_size_value is not None:
                        print(f"Placing Sell Order, Size: {sell_order_size_value}")
                        place_mkt_order('SELL', sell_order_size_value)
                    else:
                        print("Unable to retrieve account capital or bid price")

            last_ma_value = gold_MD['MA'].iloc[-2]

            for position in mt5.positions_get():
                if position.symbol == "XAUUSD":
                    if position.profit > 0:
                        # Determine if the position is long or short
                        is_long = position.type == mt5.ORDER_TYPE_BUY

                        if position.sl == float(0):
                            if is_long:
                                sl_change(position.ticket, round_down_3dp(last_ma_value))
                            else:
                                sl_change(position.ticket, round_up_3dp(last_ma_value))
                        else:
                            # For long positions, update stop loss if last MA is higher than current stop loss
                            if is_long and last_ma_value > position.sl:
                                sl_change(position.ticket, round_down_3dp(last_ma_value))

                            # For short positions, update stop loss if last MA is lower than current stop loss
                            elif not is_long and last_ma_value < position.sl:
                                sl_change(position.ticket, round_up_3dp(last_ma_value))

            now = datetime.now()
            seconds_to_next_bar = (5 - (now.minute % 5)) * 60 - now.second + 1
            time.sleep(seconds_to_next_bar)

    except KeyboardInterrupt:
        print("Data collection stopped by user")
        send_notification('Trading Algorithm', 'MA Extrema Algorithm Has Been Stopped Manually')


# Run the main function if the script is executed directly
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        send_notification("Trading Algorithm Error", f"An unexpected error occurred: {e}")

# Shutdown MetaTrader 5 connection
mt5.shutdown()
