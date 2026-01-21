#!/bin/bash

CLEANUP_JQ=false

if ! command -v jq >/dev/null 2>&1; then
    case "$OSTYPE" in
        linux*)        url="https://github.com/jqlang/jq/releases/latest/download/jq-linux64" ;;
        darwin*)       url="https://github.com/jqlang/jq/releases/latest/download/jq-macos-amd64" ;;
        msys*|cygwin*) url="https://github.com/jqlang/jq/releases/latest/download/jq-win64.exe" ;;
    esac
    curl -sL -o ./jq "$url"
    chmod +x ./jq
    JQ="./jq"
    CLEANUP_JQ=true
else
    JQ="jq"
fi

cleanup() {
    rm -f "./tmp.json"
    if [[ "$CLEANUP_JQ" == true && -f "./jq" ]]; then
        rm -f "./jq"
    fi
}
trap cleanup EXIT

export JQ

# load closest kalshi market
chmod +x demo/scripts/load_market.sh
demo/scripts/load_market.sh
case "$1" in
    index|ticker)
        mode="$1"
        ;;
    *)
    echo "Invalid signal input"
    exit 1
    ;;
esac
if [[ "$mode" == "index" ]]; then
    channel="index.ETHUSD-INDEX"
else
    channel="ticker.ETH_USD"
fi
if ! [[ "$2" =~ ^[0-9]+$ ]] || [[ "$2" -eq 0 ]]; then
    echo "Runtime must be a positive integer" >&2
    exit 1
fi
runtime="$2"
if ! [[ "$3" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    echo "Starting balance must be a number" >&2
    exit 1
fi
starting_balance="$3"
$JQ --arg terminal_exit_time "$runtime" --arg channel "$channel" --arg starting_balance "$starting_balance" '
  .risk_profile.portfolio_limits.terminal_exit_time = ($terminal_exit_time | tonumber) |
  .signal_config.signal_channels = [$channel] |
  .kalshi_market_config.starting_balance = ($starting_balance | tonumber)
  ' demo/config/config.json > tmp.json && mv tmp.json demo/config/config.json

python3 -m demo.runner.run
