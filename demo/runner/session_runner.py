import json
import asyncio
from core.client import KalshiAuthentication, KalshiAPI, KalshiWebsocket
from core.model import BSBOModel
from core.market import BinaryMarket
from core.currency_pipeline import BinanceAPI, CryptoWebsocket, VolatilityEstimator
from core.executor import OptionsExecutorSimulator
from live_trading.RiskExceptions import *
import time
import logging

logger = logging.getLogger("runner")

class TradingSessionRunner:

    def __init__(self, path_to_config: str, shutdown_event: asyncio.Event = None):
        self.load_config(path_to_config)
        self.shutdown_event = shutdown_event or asyncio.Event()

    def load_config(self, path_to_config):
        '''
        Safely loads config.
        '''
        with open(path_to_config, 'r') as file:
            data = json.load(file)

            self.kalshi_authentication_config = data.get("kalshi_authentication_config")
            self.kalshi_market_config = data.get("kalshi_market_config")
            self.signal_config = data.get("signal_config")
            self.logger_config = data.get("logger_config")
            self.risk_profile = data.get("risk_profile")
    
    def _build(self):
        '''
        Constructs the necessary objects and then calls for dependency wiring.
        '''
        self.session = KalshiAuthentication(
            path_to_private_key=self.kalshi_authentication_config["path_to_private_key"],
            access_key=self.kalshi_authentication_config["access_key"]
        )

        self.bsbo_model = BSBOModel()

        self.market = BinaryMarket(
            ticker=self.kalshi_market_config["kalshi_ticker"],
            volatility_window=self.kalshi_market_config["volatility_window"]
        )

        self.ks_api = KalshiAPI(session=self.session)
        self.ks_ws = KalshiWebsocket(session=self.session)

        self.ks_ws.set_market(self.market)

        self.vol = VolatilityEstimator(api=BinanceAPI())

        self.binance_ws = CryptoWebsocket(channels=self.signal_config["signal_channels"])

        self.executor = OptionsExecutorSimulator(
            kalshi_api=self.ks_api,
            market=self.market,
            session=self.session,
            max_inventory=self.risk_profile["portfolio_limits"]["max_inventory"],
            min_edge=self.risk_profile["trading_parameters"]["minimum_edge"],
            currency="ETH",
            strike=self.kalshi_market_config["strike"],
            expiry_datetime=self.kalshi_market_config["expiry_datetime"],
            model=self.bsbo_model,
            v_estimator=self.vol,
            fresh_data_callback=None,
            max_inventory_dev=self.risk_profile["portfolio_limits"]["max_inventory_dev"],
            max_balance_dev=self.risk_profile["portfolio_limits"]["max_balance_dev"],
            minimum_balance=self.risk_profile["portfolio_limits"]["minimum_balance"],
            starting_balance=self.kalshi_market_config["starting_balance"]
            )

        self._wire_dependencies()

    def _wire_dependencies(self):
        '''
        Wires necessary dependencies.
        '''
        self.executor.fresh_data_callback = self.binance_ws.get_tick
        self.binance_ws.get_tick
        self.binance_ws.on_index_tick = self.executor.on_tick
        self.ks_ws.set_executor(self.executor)
        self.market.on_update_callback = self.executor.on_market_update
        self.market.on_gap_callback = self.ks_ws.handle_gap
    
    async def init_and_connect(self):
        '''
        Initializes, connects, and configures all API-connected elements.
        '''

        await self.vol.api.connect()
        await self.vol.init_candles()
        await self.ks_ws.connect()
        await self.ks_ws.subscribe_orderbook(self.kalshi_market_config["kalshi_ticker"])
        await self.ks_api.connect()
        await self.executor.reconcile()

    async def start(self):
        self._build()
        self._running = True
        await self.init_and_connect()

        tasks = {asyncio.create_task(self.ks_ws.run()), asyncio.create_task(self.binance_ws.run())}

        staleness_limits = self.risk_profile["staleness_limits"]
        terminal_time = self.risk_profile["portfolio_limits"]["terminal_exit_time"]
        start_time = time.time()
        last_reconciliation = time.time()

        try:
            while tasks:
                done, pending = await asyncio.wait(tasks, timeout=1.0, return_when=asyncio.FIRST_COMPLETED)

                # Check for shutdown signal FIRST
                if self.shutdown_event.is_set():
                    logger.info("Shutdown signal detected. Closing position...")
                    await self._safe_close_position()
                    break

                for task in done:
                    try:
                        task.result()
                    except RiskLimitExceeded as e:
                        logger.error(f"Risk limit exceeded: {e}. Closing position.")
                        await self._safe_close_position()
                        return
                    except Exception as e:
                        logger.error(f"Task error: {e}")
                        await self._safe_close_position()
                        return

                now = time.time()
                await self.executor._sync_balance()

                if (now - start_time) >= terminal_time:
                    logger.info("Terminal time reached. Closing position...")
                    await self._safe_close_position()
                    break

                if time.time() >= last_reconciliation + staleness_limits["reconciliation_period"]:
                    logger.info("Periodic reconciliation started.")
                    try:
                        await self.executor.reconcile()
                    except RiskLimitExceeded as e:
                        logger.error(f"Risk limit exceeded: {e}. Closing position.")
                        await self._safe_close_position()
                        return
                    last_reconciliation = time.time()
                    logger.info("Periodic reconciliation finished.")

                if self.market.orderbook.timestamp and (time.time_ns() - self.market.orderbook.timestamp) > staleness_limits["maximum_orderbook_staleness"] * 1e9:
                    logger.error("Orderbook staleness threshold exceeded. Closing position...")
                    await self._safe_close_position()
                    break

                tasks = pending

        finally:
            # Cancel any remaining websocket tasks
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.stop()  

    async def _safe_close_position(self):
        '''
        Close position with timeout and error handling.
        '''
        try:
            await asyncio.wait_for(self.executor._close_position(), timeout=10.0)
            logger.info("Position closed successfully.")
        except asyncio.TimeoutError:
            logger.error("Position close timed out!")
        except Exception as e:
            logger.error(f"Error closing position: {e}")

    async def stop(self):
        '''
        Stop all connections. Position should already be closed.
        '''
        if not self._running:
            return

        self._running = False
        logger.info("Closing connections...")

        async def safe_close(coro, name, timeout=5.0):
            try:
                await asyncio.wait_for(coro, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"{name} close timed out")
            except Exception as e:
                logger.warning(f"{name} close error: {e}")

        await safe_close(self.ks_ws.close(), "ks_ws")
        await safe_close(self.binance_ws.stop(), "binance_ws")
        await safe_close(self.ks_api.close(), "ks_api")
        await safe_close(self.vol.api.close(), "vol_api")

        logger.info(f"Trading session ended. Final Balance: {self.executor.balance}. Final inventory: {self.executor.inventory}.")

