from freqtrade.optimize.hyperopt import IHyperOptLoss
import math
from datetime import datetime
from pandas import DataFrame, date_range
import pandas as pd
from freqtrade.data.metrics import calculate_max_drawdown
from typing import Dict, Any

# Sortino settings
TARGET_TRADES = 500
EXPECTED_MAX_PROFIT = 3.0 # x 100%
MAX_ACCEPTED_TRADE_DURATION = 180 # minutes
MIN_ACCEPTED_TRADE_DURATION = 2 # minutes
MIN_ACCEPTED_AVERAGE_TRADE_DAILY = 0.5
MIN_ACCEPTED_AVERAGE_PROFIT = 0.9

# Loss settings
# EXPECTED_MAX_PROFIT = 3.0
# WIN_LOSS_WEIGHT = 2
AVERAGE_PROFIT_WEIGHT = 1.5
AVERAGE_PROFIT_THRESHOLD = 5 # %
SORTINO_WEIGHT = 2
TOTAL_PROFIT_WEIGHT = 0.5
DRAWDOWN_WEIGHT = 3
DURATION_WEIGHT = 1
AVERAGE_TRADE_DAILY_WEIGHT = 0.5
EXPECTANCY_WEIGHT = 4

IGNORE_SMALL_PROFITS = False
SMALL_PROFITS_THRESHOLD = 0.001  # 0.1%


def sortino_daily(results: DataFrame, trade_count: int,
                  min_date: datetime, max_date: datetime,
                  *args, **kwargs) -> float:
    """
    Objective function, returns smaller number for more optimal results.

    Uses Sortino Ratio calculation.

    Sortino Ratio calculated as described in
    http://www.redrockcapital.com/Sortino__A__Sharper__Ratio_Red_Rock_Capital.pdf
    """
    resample_freq = '1D'
    slippage_per_trade_ratio = 0.0005
    days_in_year = 365
    minimum_acceptable_return = 0.0

    # apply slippage per trade to profit_ratio
    results.loc[:, 'profit_ratio_after_slippage'] = \
        results['profit_ratio'] - slippage_per_trade_ratio

    # create the index within the min_date and end max_date
    t_index = date_range(start=min_date, end=max_date, freq=resample_freq,
                         normalize=True)

    sum_daily = (
        results.resample(resample_freq, on='close_date').agg(
            {"profit_ratio_after_slippage": sum}).reindex(t_index).fillna(0)
    )

    total_profit = sum_daily["profit_ratio_after_slippage"] - minimum_acceptable_return
    expected_returns_mean = total_profit.mean()

    sum_daily['downside_returns'] = 0
    sum_daily.loc[total_profit < 0, 'downside_returns'] = total_profit
    total_downside = sum_daily['downside_returns']
    # Here total_downside contains min(0, P - MAR) values,
    # where P = sum_daily["profit_ratio_after_slippage"]
    down_stdev = math.sqrt((total_downside**2).sum() / len(total_downside))

    if down_stdev != 0:
        sortino_ratio = expected_returns_mean / down_stdev * math.sqrt(days_in_year)
    else:
        # Define high (negative) sortino ratio to be clear that this is NOT optimal.
        sortino_ratio = -20.

    # print(t_index, sum_daily, total_profit)
    # print(minimum_acceptable_return, expected_returns_mean, down_stdev, sortino_ratio)
    return -sortino_ratio

def expectancy_loss(results: DataFrame, backtest_stats: Dict[str, Any], trade_count: int) -> float:

    stake = backtest_stats['stake_amount']
    total_profit_pct = results["profit_abs"] / stake

    # Winning trades
    results['upside_returns'] = 0
    results.loc[total_profit_pct > 0.0001, 'upside_returns'] = 1.0

    if backtest_stats['wins']:
        winning_count = backtest_stats['wins']
    else:
        winning_count = results['upside_returns'].sum()

    # Losing trades
    results['downside_returns'] = 0
    results.loc[total_profit_pct < 0, 'downside_returns'] = 1.0

    w = winning_count / trade_count
    l = 1.0 - w
    results['net_gain'] = total_profit_pct * results['upside_returns']
    results['net_loss'] = total_profit_pct * results['downside_returns']
    ave_profit = results['net_gain'].sum() / trade_count
    ave_loss = results['net_loss'].sum() / trade_count

    if abs(ave_loss) < 0.01:
        ave_loss = 0.01  # set min loss = 1%, otherwise results can be wildly skewed
    r = ave_profit / abs(ave_loss)
    e = r * w - l

    expectancy_loss = -e
    
    return expectancy_loss

class GeniusLoss3(IHyperOptLoss):
    """
    Defines custom loss function which consider various metrics
    to make more robust strategy.
    Adjust those weights to get more suitable results for your strategy
    WIN_LOSS_WEIGHT
    AVERAGE_PROFIT_WEIGHT
    AVERAGE_PROFIT_THRESHOLD - upper threshold of average profit to rely on (cut off crazy av.profits like 10%+)
    SORTINO_WEIGHT
    TOTAL_PROFIT_WEIGHT


    IGNORE_SMALL_PROFITS - this param allow to filter small profits
    (to take into consideration possible spread)
    """

    @staticmethod
    def hyperopt_loss_function(results: DataFrame, trade_count: int,
                               min_date: datetime, max_date: datetime,
                               backtest_stats: Dict[str, Any],
                               *args, **kwargs) -> float:
        """
        Objective function, returns smaller number for better results.
        """
        profit_threshold = 0

        if IGNORE_SMALL_PROFITS:
            profit_threshold = SMALL_PROFITS_THRESHOLD

        # total_profit = results['profit_ratio'].sum()
        total_profit = results['profit_abs'].sum()
        total_trades = len(results)
        # total_win = len(results[(results['profit_ratio'] > profit_threshold)])
        # total_lose = len(results[(results['profit_ratio'] <= 0)])
        average_profit = results['profit_ratio'].mean() * 100
        sortino_ratio = sortino_daily(results, trade_count, min_date, max_date)
        trade_duration = results['trade_duration'].mean()
        backtest_days = (max_date - min_date).days or 1
        average_trades_per_day = round(total_trades / backtest_days, 5)

        max_drawdown = 0
        try:
            max_drawdown = calculate_max_drawdown(results, value_col='profit_abs')[0]
        except:
            pass

        # if total_lose == 0:
        #     total_lose = 1

        # profit_loss = (1 - total_profit / EXPECTED_MAX_PROFIT) * TOTAL_PROFIT_WEIGHT
        profit_loss = total_profit * TOTAL_PROFIT_WEIGHT
        # win_lose_loss = (1 - (total_win / total_lose)) * WIN_LOSS_WEIGHT
        # average_profit_loss = 1 - (min(average_profit, AVERAGE_PROFIT_THRESHOLD) * AVERAGE_PROFIT_WEIGHT)
        # average_profit_loss = 1 - (min(average_profit, AVERAGE_PROFIT_THRESHOLD) * AVERAGE_PROFIT_WEIGHT * total_trades)
        average_profit_loss = (MIN_ACCEPTED_AVERAGE_PROFIT - min(average_profit, AVERAGE_PROFIT_THRESHOLD)) * total_trades * AVERAGE_PROFIT_WEIGHT
        sortino_ratio_loss = SORTINO_WEIGHT * sortino_ratio
        drawdown_loss = max_drawdown * DRAWDOWN_WEIGHT
        # duration_loss = DURATION_WEIGHT * min(trade_duration / MAX_ACCEPTED_TRADE_DURATION, 1)
        duration_loss = DURATION_WEIGHT * (trade_duration / MAX_ACCEPTED_TRADE_DURATION) * 5
        average_trade_daily_loss = (MIN_ACCEPTED_AVERAGE_TRADE_DAILY - average_trades_per_day) * 10 * AVERAGE_TRADE_DAILY_WEIGHT
        expectancy_loss = expectancy_loss(results, backtest_stats, trade_count) * EXPECTANCY_WEIGHT
        # result = profit_loss + win_lose_loss + average_profit_loss + sortino_ratio_loss + drawdown_loss + duration_loss

        result = -profit_loss + average_profit_loss + drawdown_loss + sortino_ratio_loss + duration_loss + average_trade_daily_loss + expectancy_loss

        return result
