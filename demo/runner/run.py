from .session_runner import TradingSessionRunner    
import logging
from datetime import datetime
import asyncio
import signal
import os

logger = logging.getLogger("runner")

def setup_logging():
    
    os.makedirs("logs", exist_ok=True)
    
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    ))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fill_log = logging.getLogger("sim_fills")
    fill_log.setLevel(logging.DEBUG)
    fill_log.propagate = False 
    
    state_file_handler = logging.FileHandler(f"logs/state_{timestamp}.log", mode="w")
    state_file_handler.setLevel(logging.DEBUG) 
    state_file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    fill_log.addHandler(state_file_handler)

    order_log = logging.getLogger("sim_orders")
    order_log.setLevel(logging.DEBUG)
    order_log.propagate = False 
    
    file_handler = logging.FileHandler(f"logs/orders_{timestamp}.log", mode="w")
    file_handler.setLevel(logging.DEBUG) 
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    order_log.addHandler(file_handler)

    price_log = logging.getLogger("pricing_decisions")
    price_log.setLevel(logging.DEBUG)
    price_log.propagate = False 
    file_handler = logging.FileHandler(f"logs/prices_{timestamp}.log", mode="w")
    file_handler.setLevel(logging.DEBUG) 
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    price_log.addHandler(file_handler)

    order_log.addHandler(console)
    fill_log.addHandler(console)

    runner_log = logging.getLogger("runner")
    runner_log.setLevel(logging.DEBUG)
    runner_log.propagate = False
    runner_log.addHandler(console) 

    return

async def main():
    setup_logging()
    shutdown_event = asyncio.Event()
    
    runner = TradingSessionRunner("demo/config/config.json", shutdown_event)
    
    def handle_signal():
        logger.info("Shutdown signal received...")
        shutdown_event.set()
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)
    
    try:
        await runner.start()
    finally:
        if runner._running:
            await runner.stop()

if __name__ == "__main__":
    asyncio.run(main())