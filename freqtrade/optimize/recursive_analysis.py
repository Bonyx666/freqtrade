import logging
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pandas import DataFrame

from freqtrade.configuration import TimeRange
from freqtrade.data.history import get_timerange
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.loggers.set_log_levels import (reduce_verbosity_for_bias_tester,
                                              restore_verbosity_for_bias_tester)
from freqtrade.optimize.backtesting import Backtesting


logger = logging.getLogger(__name__)


class VarHolder:
    timerange: TimeRange
    data: DataFrame
    indicators: Dict[str, DataFrame]
    from_dt: datetime
    to_dt: datetime
    timeframe: str
    startup_candle: int

class RecursiveAnalysis:

    def __init__(self, config: Dict[str, Any], strategy_obj: Dict):
        self.failed_bias_check = True
        self.full_varHolder = VarHolder()
        self.partial_varHolder_array = []

        self.entry_varHolders: List[VarHolder] = []
        self.exit_varHolders: List[VarHolder] = []
        self.exchange: Optional[Any] = None

        # pull variables the scope of the recursive_analysis-instance
        self.local_config = deepcopy(config)
        self.local_config['strategy'] = strategy_obj['name']
        self._startup_candle = config.get('startup_candle', [199, 399, 499, 999, 1999])
        self.strategy_obj = strategy_obj

    @staticmethod
    def dt_to_timestamp(dt: datetime):
        timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())
        return timestamp

    # analyzes two data frames with processed indicators and shows differences between them.
    def analyze_indicators(self):
        
        pair_to_check = self.local_config['pairs'][0]
        logger.info(f"Start checking for recursive bias")

        # check and report signals
        base_last_row = self.full_varHolder.indicators[pair_to_check].iloc[-1]
        base_timerange = self.full_varHolder.from_dt.strftime('%Y-%m-%dT%H:%M:%S') + "-" + self.full_varHolder.to_dt.strftime('%Y-%m-%dT%H:%M:%S')
        
        for part in self.partial_varHolder_array:
            part_last_row = part.indicators[pair_to_check].iloc[-1]
            part_timerange = part.from_dt.strftime('%Y-%m-%dT%H:%M:%S') + "-" + part.to_dt.strftime('%Y-%m-%dT%H:%M:%S')

            logger.info(f"Comparing last row of {base_timerange} backtest")
            logger.info(f"vs {part_timerange} with {part.startup_candle} startup candle")
            
            compare_df = base_last_row.compare(part_last_row)
            if compare_df.shape[0] > 0:
                # print(compare_df)
                for col_name, values in compare_df.items():
                    # print(col_name)
                    if 'other' == col_name:
                        continue
                    indicators = values.index

                    for indicator in indicators:
                        values_diff = compare_df.loc[indicator]
                        values_diff_self = values_diff.loc['self']
                        values_diff_other = values_diff.loc['other']
                        difference = (values_diff_other - values_diff_self) / values_diff_self * 100
                        logger.info(f"=> found difference in indicator "
                                    f"{indicator}, with difference of "
                                    "{:.8f}%".format(difference))
                        # logger.info("base value {:.5f}".format(values_diff_self))
                        # logger.info("part value {:.5f}".format(values_diff_other))

            else:
                logger.info("No difference found. Stop the process.")
                break

    def prepare_data(self, varholder: VarHolder, pairs_to_load: List[DataFrame]):

        if 'freqai' in self.local_config and 'identifier' in self.local_config['freqai']:
            # purge previous data if the freqai model is defined
            # (to be sure nothing is carried over from older backtests)
            path_to_current_identifier = (
                Path(f"{self.local_config['user_data_dir']}/models/"
                     f"{self.local_config['freqai']['identifier']}").resolve())
            # remove folder and its contents
            if Path.exists(path_to_current_identifier):
                shutil.rmtree(path_to_current_identifier)

        prepare_data_config = deepcopy(self.local_config)
        prepare_data_config['timerange'] = (str(self.dt_to_timestamp(varholder.from_dt)) + "-" +
                                            str(self.dt_to_timestamp(varholder.to_dt)))
        prepare_data_config['exchange']['pair_whitelist'] = pairs_to_load

        backtesting = Backtesting(prepare_data_config, self.exchange)
        self.exchange = backtesting.exchange
        backtesting._set_strategy(backtesting.strategylist[0])

        varholder.data, varholder.timerange = backtesting.load_bt_data()
        backtesting.load_bt_data_detail()
        varholder.timeframe = backtesting.timeframe

        varholder.indicators = backtesting.strategy.advise_all_indicators(varholder.data)

    def fill_full_varholder(self):
        self.full_varHolder = VarHolder()

        # define datetime in human-readable format
        parsed_timerange = TimeRange.parse_timerange(self.local_config['timerange'])

        if parsed_timerange.startdt is None:
            self.full_varHolder.from_dt = datetime.fromtimestamp(0, tz=timezone.utc)
        else:
            self.full_varHolder.from_dt = parsed_timerange.startdt

        if parsed_timerange.stopdt is None:
            self.full_varHolder.to_dt = datetime.utcnow()
        else:
            self.full_varHolder.to_dt = parsed_timerange.stopdt

        self.prepare_data(self.full_varHolder, self.local_config['pairs'])

    def fill_partial_varholder(self, start_date, startup_candle):
        partial_varHolder = VarHolder()

        partial_varHolder.from_dt = start_date
        partial_varHolder.to_dt = self.full_varHolder.to_dt
        partial_varHolder.startup_candle = startup_candle

        self.local_config['startup_candle_count'] = startup_candle

        self.prepare_data(partial_varHolder, self.local_config['pairs'])

        self.partial_varHolder_array.append(partial_varHolder)

    def start(self) -> None:

        # first make a single backtest
        self.fill_full_varholder()

        reduce_verbosity_for_bias_tester()

        start_date_full = self.full_varHolder.from_dt
        end_date_full = self.full_varHolder.to_dt

        timeframe_minutes = timeframe_to_minutes(self.full_varHolder.timeframe)

        start_date_partial = end_date_full - timedelta(minutes=int(timeframe_minutes))

        for startup_candle in self._startup_candle:
            self.fill_partial_varholder(start_date_partial, int(startup_candle))

        # Restore verbosity, so it's not too quiet for the next strategy
        restore_verbosity_for_bias_tester()

        self.analyze_indicators()
