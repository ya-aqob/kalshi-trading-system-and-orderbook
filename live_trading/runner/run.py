from .session_runner import TradingSessionRunner    
import logging
from datetime import datetime
import asyncio
import signal
import os

logger = logging.getLogger("runner")

def setup_logging(runner: TradingSessionRunner):
    loggers = runner.logger_config.get("logger_list")
    console_outs = runner.logger_config.get("console_outs")
    
    os.makedirs("logs", exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for lg in loggers:
        log = logging.getLogger(lg)
        log.setLevel(logging.DEBUG)
        log.propagate = False 
        
        file_handler = logging.FileHandler(f"logs/{lg}_{timestamp}.log", mode="w")
        file_handler.setLevel(logging.DEBUG) 
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        log.addHandler(file_handler)
        
        if lg in console_outs:
            console = logging.StreamHandler()
            console.setLevel(logging.INFO)
            console.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%H:%M:%S"
            ))
            log.addHandler(console)


async def main():
    runner = TradingSessionRunner("live_trading/config/config.yaml")
    setup_logging(runner)
    
    shutdown_event = asyncio.Event()
    
    def handle_signal():
        shutdown_event.set()
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)
    
    try:
        start_task = asyncio.create_task(runner.start())
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        
        done, pending = await asyncio.wait(
            {start_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED
        )
        
        if shutdown_task in done:
            start_task.cancel()
            try:
                await start_task
            except asyncio.CancelledError:
                pass
                
    except asyncio.CancelledError:
        logger.info("Exiting...")
    finally:
        if runner._running:
            await runner.stop()


if __name__ == "__main__":
    asyncio.run(main())