# Kalshi Trading System and Orderbook

This system enables automated, algorithmic live and simulated trading in [Kalshi](https://kalshi.com/) Binary Prediction Markets. It provides an orderbook implementation and extensible executor for implementing specific algorithms and trading logic built around event-handlers and callbacks from external live data pipelines. This repository contains an example implementation and simulator for an algorithm for trading on cryptocurrency index signals in short-term "ETH/BTC above (price) at (time)" markets.

## Getting Started with Demo

The demo included in this repository simulates the execution of an algorithm that trades on edges found in hourly "ETH above (price) at (time)" markets on Kalshi. It implements the [Black-Scholes model for binary options](https://en.wikipedia.org/wiki/Black%E2%80%93Scholes_model#Binary_options) to price these markets as binary options. It is driven by live orderbook data from Kalshi and a Crypto.com data pipeline that includes spot, index, and candlestick data to calculate realized volatility and price the market.

This demo is simulated using live data. It executes orders and maintains the state locally against the live market orderbook. All orders, trade fills, and state changes are logged and printed to console to show the algorithm's trading activity. When run, the demo will load and trade against the closest-to-spot-price strike of the current hourly market.

### The Demo Algorithm

The demo trading agent executes the following basic algorithm:

ON KALSHI MARKET TICK OR CRYPTO INDEX TICK:
   1. Fetch most recent market snapshot, volatility estimate, inventory snapshot, and signal price
   2. Value the YES resolution of the market according to Black-Scholes model with data snapshots
   3. IF the valuation exceeds the ask price plus a minimum edge parameter, THEN:
      1. Buy 10 shares of YES
   4. ELSE IF the valuation is below the bid price less a minimum edge parameter, THEN:
      1. Sell 10 shares of YES
   5. ELSE
      1. Do not trade this tick

All trading activity is constrained by a set of configurable parameters and risk boundaries in the ```demo/config/config.json``` file. Orders that would exceed the risk bounds are modified accordingly, similar to the live trading system.

### Prerequisites 

1. Python3 (version 3.13 or later)
2. A venv with the packages in `requirements.txt` installed.
3. A **READ-ONLY** Kalshi API key
   1. Follow [these instructions](https://docs.kalshi.com/getting_started/api_keys) to create a new key if necessary

### Running the Demo

1. Change the working directory to this project's root directory.
2. Edit the ```path_to_private_key``` and ```access_key``` fields in ```demo/config/config.json``` to match the relative path to your private key file and the access key associated with the private key.
3. Run ```demo/run_demo.sh index <runtime> <starting_balance>``` to start the demo simulation.
   1. Runtime is the duration of the trading session in seconds (it must end before the market resolves)
   2. Starting balance is the desired starting balance of the simulation account (~50 is a good base balance)

A market should load soon after starting the simulation. Session market valuations, order placement, and state change events and data will be output to their respective files in the ```logs/``` folder. Only order placements, fills, and session state changes will be printed to the console.

## The Trading System

The trading system utilizes strict separation of concern for extensibility and flexibility for implementing, testing, and live-trading strategies and algorithms. There are three main sections: the market, the executor, and the signal pipeline.

### The Market

The state of the underlying Kalshi market is maintained and represented by a BinaryMarket object. The BinaryMarket is updated through snapshot-delta sequences through the Kalshi websocket. The market's state and orderbook utilize the sequence invariant provided by the Kalshi API to prevent drift and rebuild when the invariant is broken. It maintains a sliding window price history for volatility calculations, an up-to-date orderbook, and the fee schedule for the given market. State changes in the underlying Binary Market can trigger trading decisions through an on-update callback hook to the executor.

### The Executor

The executor is the trading agent responsible for trading decisions, order placement/cancellation, and tracking of the account porfolio/position. The base Executor implements risk limiting functions, order placement/cancellation, state management and reconciliation to facilitate other trading strategies. It utilizes and supports synchronization primitives to maintain a coherent state and trading pattern. It is abstract, and must be extended by implementing handlers for order fill events and market update events. These event handlers, along with those that can be created in the subclass for signal events, are the basis for implementing more robust and complex trading strategies.

### The Signals

Signal pipelines are specific to the trading strategy being implemented. One example included in the repository is the currency_pipeline which provides orderbook ticks and index ticks for cryptocurrencies through the Crypto.com API. Signals primarily interact/trigger trading decisions in the executor through specific-to-strategy hooks and callbacks.

## Live Trading (WIP)

The system supports live trading on Kalshi markets through a funded user account. The default trading strategy implemented in `live_trading` is the same as the demo strategy. Strategies can be changed by instantiating a different Executor agent in the `session_runner` and wiring all of the necessary dependencies accordingly.

### Prerequisites

1. Python3 (version 3.13 or later)
2. A venv with the packages in `requirements.txt` installed.
3. A **READ AND WRITE** Kalshi API key
   1. Follow [these instructions](https://docs.kalshi.com/getting_started/api_keys) to create a new key if necessary
4. Funds in the Kalshi account associated with the key

### Start Trading

1. Configure `live_trading/config/config.yaml` with the desired portfolio risk bounds and API key specifics.
2. Go to [Kalshi](https://kalshi.com/) and select the desired Crypto market to trade in.
3. Ensure that **Flip sell** is enabled in the account settings.
4. Input the market specifics in `live_trading/config/config.yaml`.
5. Run `python3 -m live_trading.runner.run` from the project root directory.
