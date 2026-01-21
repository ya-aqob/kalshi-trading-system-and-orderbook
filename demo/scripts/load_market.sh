#!/bin/bash

posix_ts=$(date +%s)

event_data=$(curl -s "https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXETHD&status=open&min_close_ts=${posix_ts}")

event_data=$($JQ '.events | sort_by(.strike_date)' <<< "$event_data")

event_ticker=$($JQ -r '.[0].event_ticker' <<< "$event_data")
event_expiry=$($JQ -r '.[0].strike_date' <<< "$event_data")

event_markets=$(curl -s "https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker=${event_ticker}")

tickers_and_prices=$($JQ '
  [.markets[] | {
    ticker: .ticker,
    strike_price: (.ticker | scan("T[0-9]{4}\\.[0-9]{2}"))
  }]
' <<< "$event_markets")

instr_data=$(curl -s "https://api.crypto.com/exchange/v1/public/get-tickers?instrument_name=ETH_USD")

instr_price=$($JQ '.result.data[0] | (((.b | tonumber) + (.k | tonumber)) / 2)' <<< "$instr_data")

match_ticker=$($JQ -r --arg price "$instr_price" '
  min_by((.strike_price | ltrimstr("T") | tonumber) - ($price | tonumber) | fabs) | .ticker
' <<< "$tickers_and_prices")

strike_price=$($JQ -rn --arg ticker "$match_ticker" '$ticker | scan("[0-9]{4}\\.[0-9]{2}")')

$JQ --arg ticker "$match_ticker" --arg strike "$strike_price"  --arg datetime "$event_expiry" '
  .kalshi_market_config.kalshi_ticker = $ticker |
  .kalshi_market_config.strike = ($strike | tonumber) |
  .kalshi_market_config.expiry_datetime = $datetime
' demo/config/config.json > tmp.json && mv tmp.json demo/config/config.json

echo "Market Loaded! Selected Kalshi Ticker: $match_ticker."