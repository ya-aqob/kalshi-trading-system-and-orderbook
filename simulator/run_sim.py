import asyncio
import signal
from .runner import SimulationRunner
import logging
import os
from datetime import datetime

# Simulation config
config = {
    "demo_private_key_path": "secret/demo_trading.txt",
    "demo_access_key": "c4b13b05-afed-4e6b-b909-a433d85b0a20",
    "private_key_path": "secret/Trading.txt",
    "access_key": "20001a26-f095-4ac7-90e5-bf3d375ec795",
    "ticker": "KXETHD-26JAN1000-T3079.99",
    "volatility_window": 100,
    "runtime": 3000,
    "max_inventory": 50,
    "min_edge": .03,
    "currency": "ETH",
    "strike": 3080,
    "expiry_datetime": "00:00 01/10/2026"
}

def setup_logging(log_dir="logs"):
    '''
    Configures console, quote, fill, and websocket logging.
    '''
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    ))
    
    quote_logger = logging.getLogger("orders")
    quote_logger.setLevel(logging.DEBUG)
    quote_file = logging.FileHandler(f"{log_dir}/orders_{timestamp}.log", mode="w")
    quote_file.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    quote_logger.addHandler(quote_file)

    fill_logger = logging.getLogger("fills")
    fill_logger.setLevel(logging.DEBUG)
    fill_file = logging.FileHandler(f"{log_dir}/fills_{timestamp}.log", mode="w")
    fill_file.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    fill_logger.addHandler(fill_file)

    ks_ws_logger = logging.getLogger("ks_websocket")
    ks_ws_logger.setLevel(logging.DEBUG)
    ks_ws_file = logging.FileHandler(f"{log_dir}/ks_websocket_{timestamp}.log", mode="w")
    ks_ws_file.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    ks_ws_logger.addHandler(ks_ws_file)
    ks_ws_logger.addHandler(console)

    der_ws_logger = logging.getLogger("der_websocket")
    der_ws_logger.setLevel(logging.DEBUG)
    der_ws_file = logging.FileHandler(f"{log_dir}/der_websocket_{timestamp}.log", mode="w")
    der_ws_file.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    der_ws_logger.addHandler(der_ws_file)
    der_ws_logger.addHandler(console)


    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)

async def main():
    '''
    Configure logging and start runner. Handles exit
    interrupts and signals.
    '''
    setup_logging()
    runner = SimulationRunner(config)
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(runner)))
    
    await runner.start()

async def shutdown(runner):
    print("\nShutting down...")
    await runner.stop()
    
    results = runner.get_results()
    print(f"Final balance: {results['final_balance']:.2f}")
    print(f"Final inventory: {results['final_inventory']}")

if __name__ == "__main__":
    asyncio.run(main())