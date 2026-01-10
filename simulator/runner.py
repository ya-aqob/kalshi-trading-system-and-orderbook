import asyncio
from derivatives_pipeline.DeribitAPI import DeribitREST, DeribitSocket
from client import Session, KalshiWebsocket
from market import BinaryMarket
from model.BSBOModel import BSBOModel
from executor.OptionsExecutorSimulator import OptionsExecutorSimulator
from client.API import KalshiAPI
from client.KSocket import KalshiWebsocket
from currency_pipeline.ParkinsonVolatility import VolatilityEstimator
from currency_pipeline.BinanceAPI import BinanceAPI

class SimulationRunner:

    def __init__(self, config: dict):

        self.config = config

    def _build(self):
        '''
        Configures all objects and wire dependencies.
        '''
        self.demo_session = Session(self.config["demo_private_key_path"], 
                               self.config["demo_access_key"]
                               )
        self.session = Session(self.config["private_key_path"], 
                               self.config["access_key"]
                               )
        self.bsbo_model = BSBOModel()

        self.market = BinaryMarket(ticker=self.config["ticker"], 
                                   volatility_window=self.config["volatility_window"],
                                    on_gap_callback=None,
                                    on_update_callback=None
                                    )
        
        self.dbit_rest = DeribitREST()
        self.dbit_ws = DeribitSocket()
        
        self.ks_api = KalshiAPI(session=self.demo_session)
        self.ks_ws = KalshiWebsocket(session=self.session)

        self.ks_ws.set_market(self.market)

        self.vol = VolatilityEstimator(api=BinanceAPI())

        self.executor = OptionsExecutorSimulator(
            kalshi_api=self.ks_api,
            market=self.market,
            session=self.session,
            max_inventory=self.config["max_inventory"],
            min_edge=self.config["min_edge"],
            deri_ws = self.dbit_ws,
            deri_rest=self.dbit_rest,
            currency=self.config["currency"],
            strike=self.config["strike"],
            expiry_datetime=self.config["expiry_datetime"],
            model=self.bsbo_model,
            vol_est=self.vol
        )

        self.dbit_ws.on_tick = self.executor.on_tick
        self.ks_ws.set_executor(self.executor)
        self.market.on_update_callback = self.executor.on_market_update
        

    async def start(self):
        '''
        Build objects, connect websocket, initialize ws subs,
        and run main websocket loop.
        '''
        self._build()
        self._running = True
        
        await self.ks_ws.connect()
        await self.ks_ws.subscribe_orderbook(self.config["ticker"])
        await self.executor.configure()
        await self.vol.api.connect()
        await self.vol.init_candles()

        try:
            await asyncio.gather(
            self.ks_ws.run(),
            self.dbit_ws.connect()
            )
        except asyncio.CancelledError:
            pass
    
    async def stop(self):
        '''
        End websocket.
        '''
        self._running = False
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_results(self) -> dict:
        '''
        Return final state of executor simulator
        attributes.
        '''
        return {
            "final_balance": self.executor.balance,
            "final_inventory": self.executor.inventory,
        }
