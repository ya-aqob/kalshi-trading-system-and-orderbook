import asyncio

from client import Session, KalshiWebsocket
from market import BinaryMarket
from model import Model
from .SimExecutor import SimulatorExecutor

class SimulationRunner:

    def __init__(self, config: dict):

        self.config = config

        self.market = None
        self.ws = None
        self.market = None
        self.model = None
        self.executor = None
        self._running = False

    def _build(self):
        '''
        Configures all objects and wire dependencies.
        '''
        self.session = Session(self.config["private_key_path"], self.config["access_key"])

        self.model = Model(k=self.config["k"], G=self.config["gamma"], runtime=self.config["runtime"])

        self.market = BinaryMarket(ticker=self.config["ticker"], volatility_window=self.config["volatility_window"],
                                    on_gap_callback=None)

        self.executor = SimulatorExecutor(
            api=None,
            model=self.model,
            market=self.market,
            session=None,
            runtime=self.config["runtime"],
            max_inventory=self.config["max_inventory"],
            start_balance=self.config["start_balance"]
        )

        self.websocket = KalshiWebsocket(
            session=self.session,
            max_retries=5
        )

        self.market.set_executor(self.executor)
        self.market.on_gap_callback = self.websocket._handle_gap
        self.websocket.set_market(self.market)

    async def start(self):
        '''
        Build objects, connect websocket, initialize ws subs,
        and run main websocket loop.
        '''
        self._build()
        self._running = True
        
        await self.websocket.connect()
        await self.websocket.subscribe_orderbook(self.config["ticker"])
    
        try:
            await self.websocket.run()
        except asyncio.CancelledError:
            pass
    
    async def stop(self):
        '''
        End websocket.
        '''
        self._running = False
        await self.websocket.close()
    
    def get_results(self) -> dict:
        '''
        Return final state of executor simulator
        attributes.
        '''
        return {
            "trade_history": self.executor.trade_history,
            "final_balance": self.executor.balance,
            "final_inventory": self.executor.inventory,
            "num_trades": len(self.executor.trade_history)
        }
