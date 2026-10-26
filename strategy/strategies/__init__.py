"""
strategies/  ——  团队成员策略包目录

每个子目录就是一个成员的策略包，必须满足 docs/STRATEGY_CONTRACT.md 的契约：
    - __init__.py 导出名为 Strategy 的类
    - Strategy 继承 framework.base.Strategy
    - 实现 on_init / on_bar / on_fill

本模块提供自动发现功能：扫描子目录，加载有效的策略包。
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Dict, List, Type

_PKG_DIR = Path(__file__).resolve().parent


def discover_packages() -> List[str]:
    """扫描 strategies/ 下所有子目录，返回 package 名列表。"""
    packages = []
    for entry in sorted(_PKG_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue
        init_file = entry / "__init__.py"
        strategy_file = entry / "strategy.py"
        if init_file.is_file() and strategy_file.is_file():
            packages.append(entry.name)
    return packages


# 分类依据外部 tqsdk-strategies README 的策略目录；未列入 README 的本地
# 策略（ma5ma10、dmn_paper、example）统一归入“其他”。
_CATEGORY_GROUPS: Dict[str, set[str]] = {
    "趋势跟踪与趋势强度类": {
        "01_double_ma", "05_turtle_trading", "06_macd_trend", "09_atr_stop_loss",
        "16_aroon_trend", "18_parabolic_sar", "19_ichimoku_cloud", "20_hull_ma",
        "22_trix_trend", "25_multiperiod_ma", "29_adx_trend_filter", "30_supertrend",
        "32_ichimoku_cloud", "36_guppy_ma", "40_momentum_acceleration",
        "41_bullish_ma_arrangement", "43_ma_crossover", "44_guppy_ma_trend",
        "64_kama_adaptive_trend", "66_chande_momentum_trend", "90_trailing_atr_pyramid",
        "92_drawdown_guard_trend",
    },
    "突破与通道类": {
        "02_boll_breakout", "04_dual_thrust", "08_cci_breakout", "10_momentum_breakout",
        "13_opening_range_breakout", "15_donchian_channel", "19_atr_channel_breakout",
        "21_keltner_channel", "28_volatility_breakout", "32_linear_regression_channel",
        "34_vwap_breakout", "37_volatility_breakout", "39_vwap_breakout_volume",
        "57_adaptive_volatility_breakout", "65_fractal_dimension_breakout",
        "67_squeeze_channel_breakout", "68_range_expansion_index", "89_time_window_breakout",
    },
    "均值回归与震荡反转类": {
        "03_rsi_mean_reversion", "07_kdj_signal", "11_mean_reversion_zscore", "12_grid_trading",
        "17_stochastic_rsi", "18_bollinger_mean_reversion", "18_vwap_mean_reversion",
        "19_williams_r", "23_pivot_point", "24_r_breaker", "31_vwap_mean_reversion",
        "33_boll_mean_reversion", "35_fibonacci_retracement", "38_boll_mean_reversion",
        "42_bollinger_mean_reversion", "45_trend_filtered_rsi", "69_intraday_vwap_band_reversion",
        "70_rsi_divergence_reversal", "71_boll_percent_b_reversion",
        "72_volatility_contraction_reversion", "73_atr_normalized_zscore",
    },
    "量价资金流类": {
        "14_volume_price_trend", "26_chaikin_money_flow", "28_obv_trend",
        "74_mfi_money_flow_reversal", "75_volume_profile_value_area", "76_open_interest_momentum",
        "77_turnover_rate_breakout", "78_negative_volume_index",
    },
    "多因子截面与组合轮动类": {
        "27_elder_triple_screen", "27_multi_factor_ranking", "46_multi_factor",
        "48_sector_rotation_multi_factor", "49_mean_variance_portfolio", "50_volatility_skew",
        "52_multi_factor_ai_prediction", "54_multi_asset_long_short_hedge",
        "55_momentum_value_factor_composite", "56_cross_section_multi_factor_ranking",
        "58_money_flow_rotation", "59_vol_momentum_composite", "60_cross_section_ml_ranking",
        "62_macro_factor_rotation", "79_cross_section_risk_parity", "80_momentum_carry_composite",
        "81_term_structure_momentum_rotation", "82_liquidity_adjusted_momentum",
        "83_regime_switching_allocation", "91_volatility_target_position",
        "93_adaptive_position_sizing",
    },
    "对冲套利与结构交易类": {
        "47_cross_market_hedge", "51_term_structure", "53_market_maker_hedge",
        "61_statistical_arbitrage", "63_cross_industry_chain_hedge", "84_calendar_spread_momentum",
        "85_crack_spread_monitor", "86_intercommodity_ratio_reversion", "87_pairs_beta_neutral",
        "88_cointegration_residual_breakout",
    },
}


def discover_strategy_catalog() -> List[dict]:
    """返回 Web 策略选择器使用的策略名与分类。"""
    category_by_package = {
        package: category
        for category, packages in _CATEGORY_GROUPS.items()
        for package in packages
    }
    return [
        {"name": package, "category": category_by_package.get(package, "其他")}
        for package in discover_packages()
    ]


def load_strategy_class(package_name: str) -> Type:
    """
    加载 strategies/<package_name>/ 并返回里面的 Strategy 类。

    若包不存在或不导出 Strategy，抛 ImportError。
    """
    full_mod = f"strategies.{package_name}"
    mod = importlib.import_module(full_mod)
    cls = getattr(mod, "Strategy", None)
    if cls is None:
        raise ImportError(f"{full_mod} 未导出 Strategy 类")
    return cls
