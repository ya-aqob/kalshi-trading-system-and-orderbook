import asyncio
import signal
from .runner import SimulationRunner
import logging
import os
from datetime import datetime

# Simulation config
config = {
    "private_key_path": "secret/kalshi_test.txt",
    "access_key": "f13a3037-44d5-44f3-870f-1fe35c459fba",
    "ticker": "KXHIGHMIA-25DEC29-B83.5",
    "volatility_window": 100,
    "runtime": 3600,
    "max_inventory": 10,
    "k": 150,
    "gamma": 0.02,
    "start_balance": 10
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
    
    quote_logger = logging.getLogger("quotes")
    quote_logger.setLevel(logging.DEBUG)
    quote_file = logging.FileHandler(f"{log_dir}/quotes_{timestamp}.log", mode="w")
    quote_file.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    quote_logger.addHandler(quote_file)

    fill_logger = logging.getLogger("fills")
    fill_logger.setLevel(logging.DEBUG)
    fill_file = logging.FileHandler(f"{log_dir}/fills_{timestamp}.log", mode="w")
    fill_file.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    fill_logger.addHandler(fill_file)

    ws_logger = logging.getLogger("websocket")
    ws_logger.setLevel(logging.DEBUG)
    ws_file = logging.FileHandler(f"{log_dir}/websocket_{timestamp}.log", mode="w")
    ws_file.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    ws_logger.addHandler(ws_file)
    ws_logger.addHandler(console)

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
    print(f"Trades: {results['num_trades']}")
    print(f"Final balance: {results['final_balance']:.2f}")
    print(f"Final inventory: {results['final_inventory']}")

if __name__ == "__main__":
    asyncio.run(main())