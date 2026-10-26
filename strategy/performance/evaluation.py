"""
performance/evaluation.py  —  CTA 策略绩效深度评价模块

对外暴露唯一接口：
    run(trades_path, daily_path, report_path, output_path)

由 run_backtest.py 在 performance_report.xlsx 生成后调用，不作为独立脚本使用。

输入:
    trades_path  : trades_{module}.csv
    daily_path   : daily_pnl_{module}.csv
    report_path  : performance_report_{module}.xlsx  ← 必须已存在
    output_path  : evaluation_report_{module}.xlsx   ← 本模块输出

输出 Sheet 列表（共 16 张）:
    品种分类 / C类综合评分 / 回撤与持续性 / 周月胜率回撤 / 年度正收益 /
    收益集中度 / 组合与板块 / 品种相关性 / 相关性矩阵 / 板块相关性 /
    手续费压力测试 / 年度收益矩阵 / 月度收益明细 / 月度综合概览 /
    周度收益明细 / 周度综合概览
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ── 阈值配置（可在此处调整） ─────────────────────────────────────────────────
CFG: dict = {
    "max_dd_period_days":    60,
    "underwater_ratio_max":  0.40,
    "max_consec_loss_days":  8,
    "min_pos_year_ratio":    0.60,
    "top3m_conc_max":        0.70,
    "bottom3m_conc_max":     0.70,
    "weekly_win_rate_min":   0.50,
    "weekly_dd_max":         0.03,
    "monthly_win_rate_min":  0.55,
    "monthly_dd_max":        0.05,
    "corr_high_threshold":   0.60,
    "stress_multipliers":    [1.5, 2.0],
}

# ── 板块映射 ──────────────────────────────────────────────────────────────────
SECTOR_MAP: dict[str, str] = {
    "RB": "黑色建材", "HC": "黑色建材", "I":  "黑色建材", "J":  "黑色建材",
    "JM": "黑色建材", "SF": "黑色建材", "SM": "黑色建材", "WR": "黑色建材", "ZC": "黑色建材",
    "CU": "有色金属", "AL": "有色金属", "ZN": "有色金属", "PB": "有色金属",
    "NI": "有色金属", "SN": "有色金属", "SS": "有色金属", "AO": "有色金属",
    "SI": "有色金属", "LC": "有色金属", "BC": "有色金属",
    "AU": "贵金属",   "AG": "贵金属",
    "SC": "能源",     "FU": "能源",     "LU": "能源",     "BU": "能源",     "PG": "能源",
    "MA": "化工",     "EG": "化工",     "EB": "化工",     "TA": "化工",     "L":  "化工",
    "PP": "化工",     "V":  "化工",     "RU": "化工",     "NR": "化工",     "BR": "化工",
    "SH": "化工",     "PF": "化工",     "UR": "化工",     "PX": "化工",     "SA": "化工",
    "FG": "化工",     "BZ": "化工",     "PR": "化工",
    "A":  "农产品",   "B":  "农产品",   "M":  "农产品",   "Y":  "农产品",   "OI": "农产品",
    "P":  "农产品",   "RM": "农产品",   "C":  "农产品",   "CS": "农产品",   "RS": "农产品",
    "CF": "软商品",   "SR": "软商品",   "AP": "软商品",   "JD": "软商品",   "LH": "软商品",
    "PK": "软商品",   "CJ": "软商品",   "EC": "软商品",   "SP": "软商品",
    "IC": "中金所",   "IF": "中金所",   "IH": "中金所",   "IM": "中金所",
    "T":  "中金所",   "TF": "中金所",   "TS": "中金所",
    "FB": "其他",     "LG": "其他",     "PS": "其他",
}


# ═════════════════════════════════════════════════════════════════════════════
# 数据加载
# ═════════════════════════════════════════════════════════════════════════════

def _load_data(
    trades_path: Path, daily_path: Path, report_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    print("  加载 trades …")
    trades = pd.read_csv(trades_path, parse_dates=["trade_date"])

    print("  加载 daily_pnl …")
    daily = pd.read_csv(daily_path, parse_dates=["date"])

    print("  加载 performance_report.xlsx …")
    xl: dict[str, pd.DataFrame] = {}
    with pd.ExcelFile(report_path) as xf:
        for sheet in xf.sheet_names:
            xl[sheet] = xf.parse(sheet)

    return trades, daily, xl


def _build_symbol_series(daily: pd.DataFrame) -> pd.DataFrame:
    agg = (
        daily
        .groupby(["date", "symbol"], as_index=False)
        .agg(
            daily_pnl=("daily_pnl", "sum"),
            commission=("commission", "sum"),
            daily_pnl_pct=("daily_pnl_pct", "mean"),
            num_trades=("num_trades", "sum"),
            win_trades=("win_trades", "sum"),
        )
    )
    agg = agg.sort_values(["symbol", "date"]).reset_index(drop=True)
    agg["net_value"] = agg.groupby("symbol")["daily_pnl_pct"].transform(
        lambda x: (1.0 + x).cumprod()
    )
    return agg


# ═════════════════════════════════════════════════════════════════════════════
# 品种分类（A / B / C）
# ═════════════════════════════════════════════════════════════════════════════

def _classify_symbols(trades: pd.DataFrame) -> pd.DataFrame:
    sym = (
        trades
        .groupby("symbol", as_index=False)
        .agg(
            gross_pnl=("pnl", "sum"),
            total_commission=("commission", "sum"),
            net_pnl=("profit", "sum"),
            trade_count=("trade_id", "count"),
        )
    )

    def _classify(row):
        if row["gross_pnl"] < 0:
            return "A", "策略方向失效，重新开发"
        elif row["net_pnl"] < 0:
            return "B", "手续费倒挂，排除或降频"
        else:
            return "C", "保留，进入细项评估"

    sym[["分类", "处置建议"]] = sym.apply(_classify, axis=1, result_type="expand")
    sym["板块"] = sym["symbol"].map(SECTOR_MAP).fillna("未知")
    sym["手续费/毛盈亏"] = sym["total_commission"] / sym["gross_pnl"].replace(0, np.nan)

    for col in ["gross_pnl", "total_commission", "net_pnl"]:
        sym[col] = (sym[col] / 10_000).round(2)

    return (
        sym
        .sort_values(["分类", "net_pnl"], ascending=[True, False])
        .reset_index(drop=True)
        .rename(columns={
            "symbol":           "品种",
            "gross_pnl":        "毛盈亏(万元)",
            "total_commission": "手续费(万元)",
            "net_pnl":          "净盈亏(万元)",
            "trade_count":      "交易次数",
        })
    )[["品种", "板块", "分类", "处置建议", "毛盈亏(万元)", "手续费(万元)", "净盈亏(万元)", "手续费/毛盈亏", "交易次数"]]


# ═════════════════════════════════════════════════════════════════════════════
# 辅助：回撤指标
# ═════════════════════════════════════════════════════════════════════════════

def _max_dd_period_days(nv: pd.Series) -> int:
    if len(nv) < 2:
        return 0
    dates = pd.DatetimeIndex(nv.index)
    vals = nv.values.astype(float)
    running_max = np.maximum.accumulate(vals)
    max_days = 0
    in_dd = False
    peak_i = 0
    for i in range(len(vals)):
        is_new_ath = (i > 0) and (running_max[i] > running_max[i - 1])
        is_uw = vals[i] < running_max[i]
        if is_new_ath and not in_dd:
            peak_i = i
        if not in_dd and is_uw:
            in_dd = True
        elif in_dd and not is_uw:
            max_days = max(max_days, (dates[i] - dates[peak_i]).days)
            in_dd = False
            if is_new_ath:
                peak_i = i
    if in_dd:
        max_days = max(max_days, (dates[-1] - dates[peak_i]).days)
    return max_days


def _underwater_ratio(nv: pd.Series) -> float:
    if len(nv) == 0:
        return 0.0
    running_max = nv.expanding().max()
    return float((nv < running_max).sum()) / len(nv)


def _max_consec_loss_days(daily_pnl: pd.Series) -> int:
    max_streak = streak = 0
    for v in daily_pnl:
        if v < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def _dd_quantiles(nv: pd.Series) -> dict[str, float]:
    zeros = {f"p{q}": 0.0 for q in (50, 75, 90, 95, 99)}
    if len(nv) < 2:
        return zeros
    running_max = nv.expanding().max()
    dd = ((nv - running_max) / running_max).where(lambda x: x < 0).dropna()
    if dd.empty:
        return zeros
    return {
        "p50": float(dd.quantile(0.50)),
        "p75": float(dd.quantile(0.75)),
        "p90": float(dd.quantile(0.90)),
        "p95": float(dd.quantile(0.95)),
        "p99": float(dd.quantile(0.99)),
    }


# ═════════════════════════════════════════════════════════════════════════════
# C类评价各维度
# ═════════════════════════════════════════════════════════════════════════════

def _drawdown_metrics(sym_series: pd.DataFrame, d_symbols: list[str]) -> pd.DataFrame:
    rows = []
    for sym in d_symbols:
        df = sym_series[sym_series["symbol"] == sym].sort_values("date")
        if df.empty:
            continue
        nv        = df.set_index("date")["net_value"]
        daily_pnl = df.set_index("date")["daily_pnl"]

        dd_period   = _max_dd_period_days(nv)
        uw_ratio    = _underwater_ratio(nv)
        consec_loss = _max_consec_loss_days(daily_pnl)
        q           = _dd_quantiles(nv)

        rows.append({
            "品种":              sym,
            "板块":              SECTOR_MAP.get(sym, "未知"),
            "最大回撤周期(天)":  dd_period,
            "达标_回撤周期":     "达标" if dd_period <= CFG["max_dd_period_days"] else "未达标",
            "水下时间占比":      uw_ratio,
            "达标_水下时间":     "达标" if uw_ratio <= CFG["underwater_ratio_max"] else "未达标",
            "最长连续亏损日":    consec_loss,
            "达标_连续亏损日":   "达标" if consec_loss <= CFG["max_consec_loss_days"] else "未达标",
            "日回撤_P50": q["p50"], "日回撤_P75": q["p75"],
            "日回撤_P90": q["p90"], "日回撤_P95": q["p95"], "日回撤_P99": q["p99"],
        })

    df_out = pd.DataFrame(rows)
    thresh = {
        "品种": "【阈值参考】", "板块": "",
        "最大回撤周期(天)":  f"≤ {CFG['max_dd_period_days']} 天",
        "达标_回撤周期": "", "水下时间占比": f"≤ {CFG['underwater_ratio_max']:.0%}",
        "达标_水下时间": "", "最长连续亏损日": f"≤ {CFG['max_consec_loss_days']} 天",
        "达标_连续亏损日": "",
        "日回撤_P50": "", "日回撤_P75": "", "日回撤_P90": "",
        "日回撤_P95": "", "日回撤_P99": "",
    }
    return pd.concat([pd.DataFrame([thresh]), df_out], ignore_index=True)


def _weekly_monthly_stats(xl_sheets: dict, d_symbols: list[str]) -> pd.DataFrame:
    weekly  = xl_sheets["周度_品种"]
    monthly = xl_sheets["月度_品种"]
    rows = []
    for sym in d_symbols:
        w = weekly[weekly["品种"] == sym]
        m = monthly[monthly["品种"] == sym]

        w_nonzero = w[w["周收益"] != 0]
        avg_w_win = float((w_nonzero["周收益"] > 0).mean()) if not w_nonzero.empty else np.nan
        max_w_dd  = w["周内最大回撤"].max()           if not w.empty else np.nan
        p90_w_dd  = w["周内最大回撤"].quantile(0.90)  if not w.empty else np.nan

        m_nonzero = m[m["月度收益"] != 0]
        avg_m_win = float((m_nonzero["月度收益"] > 0).mean()) if not m_nonzero.empty else np.nan
        max_m_dd  = m["最大回撤(月内)"].max()          if not m.empty else np.nan
        p90_m_dd  = m["最大回撤(月内)"].quantile(0.90) if not m.empty else np.nan

        rows.append({
            "品种": sym, "板块": SECTOR_MAP.get(sym, "未知"),
            "周均胜率":    avg_w_win,
            "达标_周胜率": "达标" if (not np.isnan(avg_w_win) and avg_w_win >= CFG["weekly_win_rate_min"]) else "未达标",
            "周最大回撤":  max_w_dd,
            "达标_周回撤": "达标" if (not np.isnan(max_w_dd) and max_w_dd <= CFG["weekly_dd_max"]) else "未达标",
            "周回撤P90":   p90_w_dd,
            "月均胜率":    avg_m_win,
            "达标_月胜率": "达标" if (not np.isnan(avg_m_win) and avg_m_win >= CFG["monthly_win_rate_min"]) else "未达标",
            "月最大回撤":  max_m_dd,
            "达标_月回撤": "达标" if (not np.isnan(max_m_dd) and max_m_dd <= CFG["monthly_dd_max"]) else "未达标",
            "月回撤P90":   p90_m_dd,
        })

    df_out = pd.DataFrame(rows)
    thresh = {
        "品种": "【阈值参考】", "板块": "",
        "周均胜率":    f"≥ {CFG['weekly_win_rate_min']:.0%}", "达标_周胜率": "",
        "周最大回撤":  f"≤ {CFG['weekly_dd_max']:.0%}",      "达标_周回撤": "",
        "周回撤P90":   "",
        "月均胜率":    f"≥ {CFG['monthly_win_rate_min']:.0%}", "达标_月胜率": "",
        "月最大回撤":  f"≤ {CFG['monthly_dd_max']:.0%}",       "达标_月回撤": "",
        "月回撤P90":   "",
    }
    return pd.concat([pd.DataFrame([thresh]), df_out], ignore_index=True)


def _annual_positive_years(xl_sheets: dict, d_symbols: list[str]) -> pd.DataFrame:
    annual = xl_sheets["年度_品种"]
    rows = []
    all_years: set[int] = set()

    for sym in d_symbols:
        df = annual[annual["品种"] == sym].sort_values("年份")
        if df.empty:
            continue
        total  = len(df)
        pos    = int((df["总收益"] > 0).sum())
        ratio  = pos / total
        yearly = {int(r["年份"]): r["总收益"] for _, r in df.iterrows()}
        all_years.update(yearly.keys())
        rows.append({
            "品种": sym, "板块": SECTOR_MAP.get(sym, "未知"),
            "回测年数": total, "正收益年数": pos,
            "正收益占比": ratio,
            "达标_年胜率": "达标" if ratio >= CFG["min_pos_year_ratio"] else "未达标",
            **yearly,
        })

    year_cols = sorted(all_years, reverse=True)
    df_out = pd.DataFrame(rows)
    for yr in year_cols:
        if yr not in df_out.columns:
            df_out[yr] = np.nan

    fixed_cols = ["品种", "板块", "回测年数", "正收益年数", "正收益占比", "达标_年胜率"]
    # 短区间或单品种回测可能没有 C 类品种；保留空表的列结构。
    df_out = df_out.reindex(columns=fixed_cols + year_cols)

    thresh: dict = {
        "品种": "【阈值参考】", "板块": "",
        "回测年数": "", "正收益年数": "",
        "正收益占比": f"≥ {CFG['min_pos_year_ratio']:.0%}", "达标_年胜率": "",
        **{yr: "" for yr in year_cols},
    }
    return pd.concat([pd.DataFrame([thresh]), df_out], ignore_index=True)


def _monthly_concentration(xl_sheets: dict, d_symbols: list[str]) -> pd.DataFrame:
    monthly = xl_sheets["月度_品种"]
    rows = []
    for sym in d_symbols:
        df = monthly[monthly["品种"] == sym].copy()
        if df.empty:
            continue

        prof_concs, loss_concs = [], []
        for year, grp in df.groupby("年份"):
            m = grp["月度收益"].values
            annual = m.sum()
            if annual > 1e-9:
                top3      = np.sort(m)[-3:].sum()
                pos_total = m[m > 0].sum()
                if pos_total > 1e-9:
                    prof_concs.append(top3 / pos_total)
            elif annual < -1e-9:
                neg_months = m[m < 0]
                neg_total  = neg_months.sum() if len(neg_months) > 0 else annual
                if abs(neg_total) > 1e-9:
                    bot3 = np.sort(m)[:3].sum()
                    loss_concs.append(bot3 / neg_total)

        def _safe(lst, fn):
            return fn(lst) if lst else np.nan

        avg_top3  = _safe(prof_concs, np.mean)
        max_top3  = _safe(prof_concs, np.max)
        n_exc_top = sum(1 for v in prof_concs if v > CFG["top3m_conc_max"])
        avg_bot3  = _safe(loss_concs, np.mean)
        max_bot3  = _safe(loss_concs, np.max)
        n_exc_bot = sum(1 for v in loss_concs if v > CFG["bottom3m_conc_max"])

        pass_top = max_top3 is np.nan or np.isnan(max_top3) or max_top3 <= CFG["top3m_conc_max"]  # type: ignore[arg-type]
        pass_bot = max_bot3 is np.nan or np.isnan(max_bot3) or max_bot3 <= CFG["bottom3m_conc_max"]  # type: ignore[arg-type]

        rows.append({
            "品种": sym, "板块": SECTOR_MAP.get(sym, "未知"),
            "盈利年数": len(prof_concs), "盈利年_Top3均值": avg_top3,
            "盈利年_Top3最大": max_top3,  "盈利年_超标年数": n_exc_top,
            "达标_盈利集中度": "达标" if pass_top else "未达标",
            "亏损年数": len(loss_concs), "亏损年_Bot3均值": avg_bot3,
            "亏损年_Bot3最大": max_bot3,  "亏损年_超标年数": n_exc_bot,
            "达标_亏损集中度": "达标" if pass_bot else "未达标",
        })

    return pd.DataFrame(rows)


def _correlation_analysis(
    sym_series: pd.DataFrame, d_symbols: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pivot = (
        sym_series[sym_series["symbol"].isin(d_symbols)]
        .pivot_table(index="date", columns="symbol", values="daily_pnl_pct")
        .fillna(0)
    )
    corr = pivot.corr().round(4)
    syms = corr.columns.tolist()
    pairs = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            s1, s2 = syms[i], syms[j]
            r = corr.loc[s1, s2]
            sec1, sec2 = SECTOR_MAP.get(s1, "未知"), SECTOR_MAP.get(s2, "未知")
            pairs.append({
                "品种A": s1, "板块A": sec1, "品种B": s2, "板块B": sec2,
                "相关系数": round(r, 4),
                "高度相关": "是" if r >= CFG["corr_high_threshold"] else "否",
                "同板块":   "是" if sec1 == sec2 else "否",
            })
    pairs_df = pd.DataFrame(
        pairs, columns=["品种A", "板块A", "品种B", "板块B", "相关系数", "高度相关", "同板块"]
    ).sort_values("相关系数", ascending=False).reset_index(drop=True)

    sectors = sorted({SECTOR_MAP.get(s, "未知") for s in d_symbols})
    sec_rows = []
    for i, sec_a in enumerate(sectors):
        for j, sec_b in enumerate(sectors):
            if i > j:
                continue
            sa = [s for s in d_symbols if SECTOR_MAP.get(s) == sec_a and s in corr.columns]
            sb = [s for s in d_symbols if SECTOR_MAP.get(s) == sec_b and s in corr.columns]
            if not sa or not sb:
                continue
            sub  = corr.loc[sa, sb]
            vals = [sub.loc[x, y] for x in sa for y in sb if x != y] if sec_a == sec_b else sub.values.flatten().tolist()
            avg_r = float(np.mean(vals)) if vals else np.nan
            sec_rows.append({
                "板块A": sec_a, "板块B": sec_b,
                "品种数A": len(sa), "品种数B": len(sb),
                "平均相关系数": round(avg_r, 4),
                "类型": "板块内" if sec_a == sec_b else "板块间",
            })
    sec_df = pd.DataFrame(
        sec_rows, columns=["板块A", "板块B", "品种数A", "品种数B", "平均相关系数", "类型"]
    ).sort_values("平均相关系数", ascending=False).reset_index(drop=True)

    return corr.reset_index().rename(columns={"symbol": "品种"}), pairs_df, sec_df


def _portfolio_sector_stats(sym_series: pd.DataFrame) -> pd.DataFrame:
    all_syms = sym_series["symbol"].unique().tolist()
    pivot = (
        sym_series
        .pivot_table(index="date", columns="symbol", values="daily_pnl_pct")
        .fillna(0).sort_index()
    )
    sector_groups: dict[str, list[str]] = {}
    for sym in all_syms:
        sec = SECTOR_MAP.get(sym, "未知")
        sector_groups.setdefault(sec, []).append(sym)

    groups: dict[str, list[str]] = {"【全组合】": all_syms, **sector_groups}
    rows = []
    for name, syms in groups.items():
        valid = [s for s in syms if s in pivot.columns]
        if not valid:
            continue
        dr   = pivot[valid].mean(axis=1)
        nv   = (1 + dr).cumprod()
        rmax = nv.expanding().max()
        dd_s = ((nv - rmax) / rmax).where(lambda x: x < 0)

        wr   = dr.resample("W-FRI").sum()
        w_nv = (1 + wr).cumprod()
        w_rm = w_nv.expanding().max()

        mr   = dr.resample("ME").sum()
        m_nv = (1 + mr).cumprod()
        m_rm = m_nv.expanding().max()

        rows.append({
            "名称":        name,
            "品种数":      len(valid),
            "日胜率":      float((dr > 0).mean()),
            "日最大回撤":  float(dd_s.min()) if dd_s.notna().any() else 0.0,
            "日回撤P90":   float(dd_s.dropna().quantile(0.90)) if dd_s.notna().any() else 0.0,
            "周胜率":      float((wr > 0).mean()) if len(wr) > 0 else np.nan,
            "周最大回撤":  float(((w_nv - w_rm) / w_rm).min()) if len(w_nv) > 1 else np.nan,
            "月胜率":      float((mr > 0).mean()) if len(mr) > 0 else np.nan,
            "月最大回撤":  float(((m_nv - m_rm) / m_rm).min()) if len(m_nv) > 1 else np.nan,
        })
    return pd.DataFrame(rows)


def _monthly_returns_detail(xl_sheets: dict, d_symbols: list[str]) -> pd.DataFrame:
    monthly = xl_sheets["月度_品种"].copy()
    monthly = monthly[monthly["品种"].isin(d_symbols)]
    monthly["年份"] = monthly["年份"].astype(int)
    monthly["月份"] = monthly["月份"].astype(int)

    pivot = monthly.pivot_table(
        index=["品种", "年份"], columns="月份", values="月度收益", aggfunc="first"
    )
    pivot.columns = [f"{int(c)}月" for c in pivot.columns]
    pivot = pivot.reset_index()
    pivot["板块"] = pivot["品种"].map(lambda s: SECTOR_MAP.get(s, "未知"))

    month_cols = [f"{m}月" for m in range(1, 13) if f"{m}月" in pivot.columns]
    pivot["全年合计"] = pivot[month_cols].sum(axis=1)
    pivot["_sec"] = pivot["品种"].map(lambda s: SECTOR_MAP.get(s, "未知"))
    pivot = pivot.sort_values(["_sec", "品种", "年份"], ascending=[True, True, False]).drop(columns=["_sec"])
    return pivot[["品种", "板块", "年份"] + month_cols + ["全年合计"]].reset_index(drop=True)


def _weekly_returns_detail(xl_sheets: dict, d_symbols: list[str]) -> pd.DataFrame:
    weekly = xl_sheets["周度_品种"].copy()
    weekly = weekly[weekly["品种"].isin(d_symbols)]
    weekly["年份"] = weekly["年份"].astype(int)
    weekly["周次"] = weekly["周次"].astype(int)
    weekly = weekly[weekly["年份"] < 2026]

    pivot = weekly.pivot_table(
        index=["年份", "品种"], columns="周次", values="周收益", aggfunc="first"
    )
    pivot.columns = [f"W{int(c):02d}" for c in pivot.columns]
    pivot = pivot.reset_index()
    pivot["板块"] = pivot["品种"].map(lambda s: SECTOR_MAP.get(s, "未知"))

    week_cols = [f"W{w:02d}" for w in range(1, 54) if f"W{w:02d}" in pivot.columns]
    pivot["全年合计"] = pivot[week_cols].sum(axis=1)
    pivot = pivot.sort_values(["年份", "品种"], ascending=[False, True])
    return pivot[["年份", "品种", "板块"] + week_cols + ["全年合计"]].reset_index(drop=True)


def _weekly_returns_overview(xl_sheets: dict, d_symbols: list[str]) -> dict:
    weekly = xl_sheets["周度_品种"].copy()
    weekly = weekly[weekly["品种"].isin(d_symbols)]
    weekly["年份"] = weekly["年份"].astype(int)
    weekly["周次"] = weekly["周次"].astype(int)
    weekly = weekly[weekly["年份"] < 2026]

    agg = (
        weekly.groupby(["年份", "周次"])["周收益"]
        .agg(avg_return="mean",
             pos_count=lambda x: int((x > 0).sum()),
             total_count="count")
        .reset_index()
    )

    def _pivot(col):
        p = agg.pivot_table(index="年份", columns="周次", values=col)
        p.columns = [f"W{int(c):02d}" for c in p.columns]
        return p.sort_index(ascending=False)

    avg_p   = _pivot("avg_return")
    pos_raw = _pivot("pos_count")
    tot_raw = _pivot("total_count")

    week_cols = [f"W{w:02d}" for w in range(1, 54) if f"W{w:02d}" in avg_p.columns]
    avg_p["全年均值"] = avg_p[week_cols].mean(axis=1)
    avg_df = avg_p.reset_index()

    count_str = pos_raw.copy().astype(object)
    for col in pos_raw.columns:
        for idx in pos_raw.index:
            p = pos_raw.loc[idx, col]
            t = tot_raw.loc[idx, col] if col in tot_raw.columns else np.nan
            count_str.loc[idx, col] = (
                f"{int(p)}/{int(t)}" if (pd.notna(p) and pd.notna(t)) else ""
            )
    return {"avg": avg_df, "count": count_str.reset_index(), "week_cols": week_cols}


def _monthly_returns_overview(xl_sheets: dict, d_symbols: list[str]) -> dict:
    monthly = xl_sheets["月度_品种"].copy()
    monthly = monthly[monthly["品种"].isin(d_symbols)]
    monthly["年份"] = monthly["年份"].astype(int)
    monthly["月份"] = monthly["月份"].astype(int)
    total_n = len(d_symbols)

    agg = (
        monthly.groupby(["年份", "月份"])["月度收益"]
        .agg(avg_return="mean", pos_count=lambda x: int((x > 0).sum()))
        .reset_index()
    )

    def _pivot(col):
        p = agg.pivot_table(index="年份", columns="月份", values=col)
        p.columns = [f"{int(c)}月" for c in p.columns]
        return p.sort_index(ascending=False)

    avg_p = _pivot("avg_return")
    month_cols = [f"{m}月" for m in range(1, 13) if f"{m}月" in avg_p.columns]
    avg_p["全年均值"] = avg_p[month_cols].mean(axis=1)
    avg_df = avg_p.reset_index()

    pos_p = _pivot("pos_count")
    for col in pos_p.columns:
        pos_p[col] = pos_p[col].apply(lambda x: f"{int(x)}/{total_n}" if pd.notna(x) else "")
    return {"avg": avg_df, "count": pos_p.reset_index(), "month_cols": month_cols}


def _annual_returns_matrix(xl_sheets: dict) -> pd.DataFrame:
    annual = xl_sheets["年度_品种"].copy()
    annual["年份"] = annual["年份"].astype(int)

    pivot = annual.pivot_table(index="年份", columns="品种", values="总收益", aggfunc="first")
    pivot = pivot.sort_index()
    symbols_sorted = sorted(pivot.columns.tolist(), key=lambda s: (SECTOR_MAP.get(s, "未知"), s))
    pivot = pivot[symbols_sorted]

    pivot.insert(0, "负收益品种数", (pivot < 0).sum(axis=1))
    pivot.insert(0, "正收益品种数", (pivot > 0).sum(axis=1))
    return pivot.reset_index()


def _commission_stress_test(trades: pd.DataFrame) -> pd.DataFrame:
    sym = (
        trades.groupby("symbol", as_index=False)
        .agg(gross_pnl=("pnl", "sum"), total_commission=("commission", "sum"), net_pnl=("profit", "sum"))
    )
    sym["板块"] = sym["symbol"].map(SECTOR_MAP).fillna("未知")

    for mult in CFG["stress_multipliers"]:
        col = f"净盈亏_×{mult}(万元)"
        sym[col] = ((sym["gross_pnl"] - sym["total_commission"] * mult) / 10_000).round(2)
        sym[f"达标_×{mult}"] = sym[col].apply(lambda x: "达标" if x > 0 else "未达标")

    def _label(row):
        if row["net_pnl"] <= 0:
            return "失效"
        if row.get("净盈亏_×1.5(万元)", 1) <= 0:
            return "脆弱"
        return "健康"

    sym["风险标签"] = sym.apply(_label, axis=1)
    for col in ["gross_pnl", "total_commission", "net_pnl"]:
        sym[col] = (sym[col] / 10_000).round(2)

    return (
        sym.sort_values(["风险标签", "net_pnl"], ascending=[True, False])
        .reset_index(drop=True)
        .rename(columns={
            "symbol": "品种", "gross_pnl": "毛盈亏(万元)",
            "total_commission": "手续费(万元)", "net_pnl": "净盈亏(万元)",
        })
    )


def _build_d_class_summary(
    d_symbols: list[str], dd_df: pd.DataFrame, wm_df: pd.DataFrame,
    yr_df: pd.DataFrame, conc_df: pd.DataFrame, stress_df: pd.DataFrame,
) -> pd.DataFrame:
    if not d_symbols:
        return pd.DataFrame(columns=["品种", "板块", "达标项数", "总评估项", "达标率"])
    criteria = [
        (dd_df,     "达标_回撤周期",    f"回撤周期 ≤ {CFG['max_dd_period_days']}天"),
        (dd_df,     "达标_水下时间",    f"水下占比 ≤ {CFG['underwater_ratio_max']:.0%}"),
        (dd_df,     "达标_连续亏损日",  f"连亏日 ≤ {CFG['max_consec_loss_days']}"),
        (wm_df,     "达标_周胜率",      f"周胜率 ≥ {CFG['weekly_win_rate_min']:.0%}"),
        (wm_df,     "达标_周回撤",      f"周回撤 ≤ {CFG['weekly_dd_max']:.0%}"),
        (wm_df,     "达标_月胜率",      f"月胜率 ≥ {CFG['monthly_win_rate_min']:.0%}"),
        (wm_df,     "达标_月回撤",      f"月回撤 ≤ {CFG['monthly_dd_max']:.0%}"),
        (yr_df,     "达标_年胜率",      f"正收益年 ≥ {CFG['min_pos_year_ratio']:.0%}"),
        (conc_df,   "达标_盈利集中度",  f"盈利Top3 ≤ {CFG['top3m_conc_max']:.0%}"),
        (conc_df,   "达标_亏损集中度",  f"亏损Bot3 ≤ {CFG['bottom3m_conc_max']:.0%}"),
        (stress_df, "达标_×1.5",        "手续费×1.5仍盈利"),
        (stress_df, "达标_×2.0",        "手续费×2.0仍盈利"),
    ]
    rows = []
    for sym in d_symbols:
        row: dict = {"品种": sym, "板块": SECTOR_MAP.get(sym, "未知")}
        pass_n = total_n = 0
        for src_df, col, label in criteria:
            match = src_df[src_df["品种"] == sym]
            val = match.iloc[0][col] if (not match.empty and col in src_df.columns) else "N/A"
            row[label] = val
            if val != "N/A":
                total_n += 1
                if val == "达标":
                    pass_n += 1
        row["达标项数"] = pass_n
        row["总评估项"] = total_n
        row["达标率"]   = f"{pass_n}/{total_n}"
        rows.append(row)

    return (
        pd.DataFrame(rows)
        .sort_values(["达标项数", "品种"], ascending=[False, True])
        .reset_index(drop=True)
    )


# ═════════════════════════════════════════════════════════════════════════════
# Excel 写入
# ═════════════════════════════════════════════════════════════════════════════

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
_THRESH_FILL = PatternFill("solid", fgColor="E2EFDA")
_THRESH_FONT = Font(bold=True, italic=True, color="375623", size=9)
_PASS_FILL   = PatternFill("solid", fgColor="C6EFCE")
_PASS_FONT   = Font(color="375623")
_FAIL_FILL   = PatternFill("solid", fgColor="FFC7CE")
_FAIL_FONT   = Font(color="9C0006")
_WARN_FILL   = PatternFill("solid", fgColor="FFEB9C")
_WARN_FONT   = Font(color="9C5700")
_ALT_FILL    = PatternFill("solid", fgColor="F2F2F2")
_TITLE_FONT  = Font(bold=True, size=11, color="1F3864")

_PCT_KEYWORDS  = ("率", "占比", "相关", "回撤", "集中度", "贡献", "胜率",
                  "P50", "P75", "P90", "P95", "P99")
_YUAN_KEYWORDS = ("万元",)


def _apply_row_format(ws, row_num: int, headers: list, values: list):
    is_thresh = values and str(values[0]) == "【阈值参考】"
    for col_idx, (h, v) in enumerate(zip(headers, values), 1):
        cell = ws.cell(row_num, col_idx)
        if is_thresh:
            cell.fill = _THRESH_FILL
            cell.font = _THRESH_FONT
            cell.alignment = Alignment(horizontal="center")
            continue
        if isinstance(v, str):
            if v == "达标":
                cell.fill, cell.font = _PASS_FILL, _PASS_FONT
            elif v == "未达标":
                cell.fill, cell.font = _FAIL_FILL, _FAIL_FONT
            elif v == "脆弱":
                cell.fill, cell.font = _WARN_FILL, _WARN_FONT
            elif v in ("A", "B"):
                cell.fill, cell.font = _FAIL_FILL, _FAIL_FONT
            elif v == "C":
                cell.fill, cell.font = _PASS_FILL, _PASS_FONT
        if isinstance(v, float) and not np.isnan(v):
            h_str = str(h)
            if any(kw in h_str for kw in _PCT_KEYWORDS):
                cell.number_format = "0.00%"
            elif any(kw in h_str for kw in _YUAN_KEYWORDS):
                cell.number_format = "#,##0.00"


def _write_df_to_sheet(ws, df: pd.DataFrame, title: str):
    if title:
        ws.append([title])
        ws.cell(ws.max_row, 1).font = _TITLE_FONT
        ws.append([])
    headers = df.columns.tolist()
    ws.append(headers)
    hdr_row = ws.max_row
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(hdr_row, col_idx)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    for r_idx, tup in enumerate(df.itertuples(index=False), 1):
        vals = list(tup)
        ws.append(vals)
        row_num = ws.max_row
        if r_idx % 2 == 0:
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row_num, col_idx)
                if c.fill.fgColor.rgb in ("00000000", "FFFFFFFF"):
                    c.fill = _ALT_FILL
        _apply_row_format(ws, row_num, headers, vals)
    freeze_row = 3 if title else 2
    ws.freeze_panes = ws.cell(freeze_row, 1)
    for col_idx, col_cells in enumerate(ws.columns, 1):
        max_w = max(sum(2 if ord(c) > 127 else 1 for c in str(cell.value or "")) for cell in col_cells)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_w + 2, 45)


def _write_weekly_detail_sheet(ws, df: pd.DataFrame, title: str):
    _POS = (PatternFill("solid", fgColor="C6EFCE"), Font(color="375623"))
    _NEG = (PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006"))

    def _is_ret(h): return str(h).startswith("W") or h == "全年合计"

    if title:
        ws.append([title]); ws.cell(ws.max_row, 1).font = _TITLE_FONT; ws.append([])
    headers = df.columns.tolist()
    ret_idxs = {i for i, h in enumerate(headers, 1) if _is_ret(h)}
    ws.append(headers)
    hdr_row = ws.max_row
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(hdr_row, col_idx)
        c.fill = _HEADER_FILL; c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)

    prev_yr = None; grp_even = False
    for tup in df.itertuples(index=False):
        vals = list(tup); ws.append(vals); row_num = ws.max_row
        cur_yr = vals[0]
        if cur_yr != prev_yr:
            prev_yr = cur_yr; grp_even = not grp_even
        if grp_even:
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row_num, col_idx)
                if c.fill.fgColor.rgb in ("00000000", "FFFFFFFF"):
                    c.fill = _ALT_FILL
        for col_idx in ret_idxs:
            v = vals[col_idx - 1]; cell = ws.cell(row_num, col_idx)
            if isinstance(v, float) and not np.isnan(v):
                cell.number_format = "0.00%"
                if v > 0: cell.fill, cell.font = _POS
                elif v < 0: cell.fill, cell.font = _NEG

    freeze_row = 3 if title else 2
    ws.freeze_panes = ws.cell(freeze_row, 4)
    for col_idx, col_cells in enumerate(ws.columns, 1):
        h = headers[col_idx - 1]
        ws.column_dimensions[get_column_letter(col_idx)].width = (
            7 if _is_ret(h) else
            min(max(sum(2 if ord(c) > 127 else 1 for c in str(cell.value or "")) for cell in col_cells) + 2, 20)
        )


def _write_overview_sheet(ws, data: dict, title: str, *, is_weekly: bool):
    _POS = (PatternFill("solid", fgColor="C6EFCE"), Font(color="375623"))
    _NEG = (PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006"))
    _SEC_FONT = Font(bold=True, size=10, color="1F3864")

    avg_df   = data["avg"]
    count_df = data["count"]
    ret_key  = "week_cols" if is_weekly else "month_cols"
    ret_cols = set(data[ret_key]) | {"全年均值"}

    def _block(block_df, block_title, color):
        ws.append([block_title]); ws.cell(ws.max_row, 1).font = _SEC_FONT
        hdrs = block_df.columns.tolist(); ws.append(hdrs)
        for ci, h in enumerate(hdrs, 1):
            c = ws.cell(ws.max_row, ci); c.fill = _HEADER_FILL; c.font = _HEADER_FONT
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        for ri, tup in enumerate(block_df.itertuples(index=False), 1):
            vals = list(tup); ws.append(vals); rn = ws.max_row
            if ri % 2 == 0:
                for ci in range(1, len(hdrs) + 1):
                    c = ws.cell(rn, ci)
                    if c.fill.fgColor.rgb in ("00000000", "FFFFFFFF"): c.fill = _ALT_FILL
            for ci, (h, v) in enumerate(zip(hdrs, vals), 1):
                cell = ws.cell(rn, ci); cell.alignment = Alignment(horizontal="center")
                if color and h in ret_cols and isinstance(v, float) and not np.isnan(v):
                    cell.number_format = "0.00%"
                    if v > 0: cell.fill, cell.font = _POS
                    elif v < 0: cell.fill, cell.font = _NEG

    if title: ws.append([title]); ws.cell(ws.max_row, 1).font = _TITLE_FONT; ws.append([])
    _block(avg_df, "等权平均周收益" if is_weekly else "等权平均月度收益", color=True)
    ws.append([]); ws.append([])
    _block(count_df,
           "正收益品种数 / 当周实际C类品种数" if is_weekly else "月度正收益品种数 / C类品种总数",
           color=False)
    ws.freeze_panes = ws.cell(4, 2)
    for col_idx, col_cells in enumerate(ws.columns, 1):
        max_w = max(sum(2 if ord(c) > 127 else 1 for c in str(cell.value or "")) for cell in col_cells)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_w + 2, 14)


def _write_monthly_detail_sheet(ws, df: pd.DataFrame, title: str):
    _POS = (PatternFill("solid", fgColor="C6EFCE"), Font(color="375623"))
    _NEG = (PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006"))

    def _is_ret(h): return str(h).endswith("月") or h == "全年合计"

    if title: ws.append([title]); ws.cell(ws.max_row, 1).font = _TITLE_FONT; ws.append([])
    headers = df.columns.tolist()
    ret_idxs = {i for i, h in enumerate(headers, 1) if _is_ret(h)}
    ws.append(headers)
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(ws.max_row, col_idx); c.fill = _HEADER_FILL; c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)

    prev_sym = None; _grp_even = False
    for r_idx, tup in enumerate(df.itertuples(index=False), 1):
        vals = list(tup); ws.append(vals); row_num = ws.max_row; cur_sym = vals[0]
        if cur_sym != prev_sym: prev_sym = cur_sym; _grp_even = (r_idx % 2 == 0)
        base_fill = _ALT_FILL if _grp_even else None
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row_num, col_idx)
            if base_fill and cell.fill.fgColor.rgb in ("00000000", "FFFFFFFF"): cell.fill = base_fill
        for col_idx in ret_idxs:
            v = vals[col_idx - 1]; cell = ws.cell(row_num, col_idx)
            if isinstance(v, float) and not np.isnan(v):
                cell.number_format = "0.00%"
                if v > 0: cell.fill, cell.font = _POS
                elif v < 0: cell.fill, cell.font = _NEG

    freeze_row = 3 if title else 2
    ws.freeze_panes = ws.cell(freeze_row, 4)
    for col_idx, col_cells in enumerate(ws.columns, 1):
        h = headers[col_idx - 1]
        ws.column_dimensions[get_column_letter(col_idx)].width = (
            8 if _is_ret(h) else
            min(max(sum(2 if ord(c) > 127 else 1 for c in str(cell.value or "")) for cell in col_cells) + 2, 20)
        )


def _write_annual_matrix_sheet(ws, df: pd.DataFrame, title: str):
    _POS = (PatternFill("solid", fgColor="C6EFCE"), Font(color="375623"))
    _NEG = (PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006"))
    fixed = {"年份", "正收益品种数", "负收益品种数"}

    if title: ws.append([title]); ws.cell(ws.max_row, 1).font = _TITLE_FONT; ws.append([])
    headers = df.columns.tolist()
    inst_idxs = {ci for ci, h in enumerate(headers, 1) if h not in fixed}
    ws.append(headers)
    for ci, h in enumerate(headers, 1):
        c = ws.cell(ws.max_row, ci); c.fill = _HEADER_FILL; c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    for tup in df.itertuples(index=False):
        vals = list(tup); ws.append(vals); row_num = ws.max_row
        for ci, (h, v) in enumerate(zip(headers, vals), 1):
            cell = ws.cell(row_num, ci)
            if ci in inst_idxs and isinstance(v, float) and not np.isnan(v):
                cell.number_format = "0.00%"
                if v > 0: cell.fill, cell.font = _POS
                elif v < 0: cell.fill, cell.font = _NEG
            else:
                cell.alignment = Alignment(horizontal="center")
    freeze_row = 3 if title else 2
    ws.freeze_panes = ws.cell(freeze_row, 4)
    for col_idx, col_cells in enumerate(ws.columns, 1):
        h = headers[col_idx - 1]
        ws.column_dimensions[get_column_letter(col_idx)].width = (
            8 if h not in fixed and h != "年份" else
            min(max(sum(2 if ord(c) > 127 else 1 for c in str(cell.value or "")) for cell in col_cells) + 2, 20)
        )


def _write_annual_years_sheet(ws, df: pd.DataFrame, title: str):
    _POS = (PatternFill("solid", fgColor="C6EFCE"), Font(color="375623"))
    _NEG = (PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006"))

    def _is_yr(h):
        try: return 2000 <= int(h) <= 2100
        except: return False  # noqa: E722

    if title: ws.append([title]); ws.cell(ws.max_row, 1).font = _TITLE_FONT; ws.append([])
    headers = df.columns.tolist()
    yr_idxs = {ci for ci, h in enumerate(headers, 1) if _is_yr(h)}
    ws.append(headers)
    for ci, h in enumerate(headers, 1):
        c = ws.cell(ws.max_row, ci); c.fill = _HEADER_FILL; c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    for r_idx, tup in enumerate(df.itertuples(index=False), 1):
        vals = list(tup); ws.append(vals); row_num = ws.max_row
        is_thresh = str(vals[0]) == "【阈值参考】"
        if is_thresh:
            for ci in range(1, len(headers) + 1):
                cell = ws.cell(row_num, ci)
                cell.fill = _THRESH_FILL; cell.font = _THRESH_FONT
                cell.alignment = Alignment(horizontal="center")
            continue
        if r_idx % 2 == 0:
            for ci in range(1, len(headers) + 1):
                c = ws.cell(row_num, ci)
                if c.fill.fgColor.rgb in ("00000000", "FFFFFFFF"): c.fill = _ALT_FILL
        _apply_row_format(ws, row_num, headers, vals)
        for ci in yr_idxs:
            v = vals[ci - 1]; cell = ws.cell(row_num, ci)
            if isinstance(v, float) and not np.isnan(v):
                cell.number_format = "0.00%"
                if v > 0: cell.fill, cell.font = _POS
                elif v < 0: cell.fill, cell.font = _NEG
    freeze_row = 3 if title else 2
    ws.freeze_panes = ws.cell(freeze_row, 1)
    for col_idx, col_cells in enumerate(ws.columns, 1):
        h = headers[col_idx - 1]
        ws.column_dimensions[get_column_letter(col_idx)].width = (
            9 if _is_yr(h) else
            min(max(sum(2 if ord(c) > 127 else 1 for c in str(cell.value or "")) for cell in col_cells) + 2, 30)
        )


# ═════════════════════════════════════════════════════════════════════════════
# 杠杆统计（组合专属）
# ═════════════════════════════════════════════════════════════════════════════

def _build_leverage_df(portfolio_daily_path) -> pd.DataFrame:
    """读取 daily_pnl_portfolio_*.csv，生成年度杠杆统计表。"""
    port = pd.read_csv(portfolio_daily_path, parse_dates=["date"])
    if "daily_leverage" not in port.columns:
        return pd.DataFrame(columns=["时间段", "均值", "最大值", "P50", "P75", "P95"])

    lev = port[["date", "daily_leverage"]].dropna(subset=["daily_leverage"]).copy()
    lev["年份"] = lev["date"].dt.year

    def _row(name, s):
        return {
            "时间段": str(name),
            "均值":   round(float(s.mean()),          4),
            "最大值": round(float(s.max()),            4),
            "P50":    round(float(s.quantile(0.50)),   4),
            "P75":    round(float(s.quantile(0.75)),   4),
            "P95":    round(float(s.quantile(0.95)),   4),
        }

    rows = [_row("全样本", lev["daily_leverage"])]
    for yr, grp in lev.groupby("年份"):
        rows.append(_row(yr, grp["daily_leverage"]))
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════════
# 策略贡献分析（组合专属）
# ═════════════════════════════════════════════════════════════════════════════

def _build_strat_contrib_overview(
    strat_df: pd.DataFrame, port_daily: pd.DataFrame
) -> pd.DataFrame:
    """全样本各策略收益贡献汇总表（口径B：净贡献 / 组合净盈亏）。"""
    strat_cols = [c for c in strat_df.columns if c not in ("date", "total")]
    port_net   = float(port_daily["daily_pnl_pct"].sum())

    rows = []
    for col in strat_cols:
        net = float(strat_df[col].sum())
        pos = int((strat_df[col] > 0).sum())
        neg = int((strat_df[col] < 0).sum())
        rows.append({
            "策略":       col,
            "净贡献":     round(net, 6),
            "贡献占比":   round(net / port_net, 4) if abs(port_net) > 1e-10 else np.nan,
            "正贡献天数": pos,
            "负贡献天数": neg,
            "日胜率":     round(pos / len(strat_df), 4) if len(strat_df) > 0 else 0.0,
        })

    rows.append({
        "策略":       "组合合计",
        "净贡献":     round(port_net, 6),
        "贡献占比":   1.0,
        "正贡献天数": int((port_daily["daily_pnl_pct"] > 0).sum()),
        "负贡献天数": int((port_daily["daily_pnl_pct"] < 0).sum()),
        "日胜率":     round(float((port_daily["daily_pnl_pct"] > 0).mean()), 4),
    })
    return pd.DataFrame(rows)


def _build_strat_contrib_pivot(strat_df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """
    按时间粒度（年/月/周）汇总每策略的 daily_pnl_pct 贡献。

    返回 DataFrame：行 = 时间段，列 = 策略 key + 合计，值 = sum(daily_pnl_pct)。
    """
    strat_cols = [c for c in strat_df.columns if c not in ("date", "total")]
    if not strat_cols:
        return pd.DataFrame()

    df = strat_df[["date"] + strat_cols].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")

    try:
        period_sum = df.resample(freq).sum()
    except ValueError:
        fallback = {"YE": "A", "ME": "M"}
        period_sum = df.resample(fallback.get(freq, freq)).sum()

    if freq in ("YE", "A", "Y"):
        period_sum.index = period_sum.index.year.astype(str)
        col_name = "年份"
    elif freq in ("ME", "M"):
        period_sum.index = period_sum.index.to_period("M").strftime("%Y-%m")
        col_name = "年月"
    else:
        period_sum.index = pd.Index([
            f"{d.year}-W{d.isocalendar()[1]:02d}" for d in period_sum.index
        ])
        col_name = "年周"

    period_sum.index.name = col_name
    period_sum["合计"] = period_sum[strat_cols].sum(axis=1)

    return (
        period_sum.reset_index()
        .sort_values(col_name, ascending=False)
        .reset_index(drop=True)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Excel writer：策略贡献热力表
# ─────────────────────────────────────────────────────────────────────────────

def _write_contribution_heatmap(ws, df: pd.DataFrame, title: str):
    """写入策略贡献热力矩阵：正值绿色，负值红色，百分比格式。"""
    _POS = (PatternFill("solid", fgColor="C6EFCE"), Font(color="375623"))
    _NEG = (PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006"))

    if title:
        ws.append([title])
        ws.cell(ws.max_row, 1).font = _TITLE_FONT
        ws.append([])

    if df.empty:
        ws.append(["无数据"])
        return

    headers = df.columns.tolist()
    ws.append(headers)
    hdr_row = ws.max_row
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(hdr_row, col_idx)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)

    numeric_col_idxs = set(range(2, len(headers) + 1))

    for r_idx, tup in enumerate(df.itertuples(index=False), 1):
        vals = list(tup)
        ws.append(vals)
        row_num = ws.max_row
        if r_idx % 2 == 0:
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row_num, col_idx)
                if c.fill.fgColor.rgb in ("00000000", "FFFFFFFF"):
                    c.fill = _ALT_FILL
        for col_idx in numeric_col_idxs:
            v = vals[col_idx - 1]
            cell = ws.cell(row_num, col_idx)
            if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)):
                cell.number_format = "0.00%"
                if v > 0:
                    cell.fill, cell.font = _POS
                elif v < 0:
                    cell.fill, cell.font = _NEG

    freeze_row = 3 if title else 2
    ws.freeze_panes = ws.cell(freeze_row, 2)

    first_col_cells = list(ws.columns)[0]
    first_col_w = max(
        sum(2 if ord(ch) > 127 else 1 for ch in str(cell.value or ""))
        for cell in first_col_cells
    )
    ws.column_dimensions[get_column_letter(1)].width = min(first_col_w + 2, 20)
    for col_idx in numeric_col_idxs:
        ws.column_dimensions[get_column_letter(col_idx)].width = 12


def _write_excel(output_path: Path, sheets: dict[str, tuple]):
    wb = Workbook()
    wb.remove(wb.active)
    for sheet_name, sheet_data in sheets.items():
        ws = wb.create_sheet(sheet_name)
        if len(sheet_data) == 3:
            df, title, writer_fn = sheet_data
            writer_fn(ws, df, title)
        else:
            df, title = sheet_data
            _write_df_to_sheet(ws, df, title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


# ═════════════════════════════════════════════════════════════════════════════
# 对外接口
# ═════════════════════════════════════════════════════════════════════════════

def run(
    trades_path:          Path,
    daily_path:           Path,
    report_path:          Path,
    output_path:          Path,
    strategy_daily_path:  "Path | None" = None,
    portfolio_daily_path: "Path | None" = None,
) -> None:
    print("=== CTA 策略绩效深度评价 ===")

    print("[1/9] 加载数据 …")
    trades, daily, xl_sheets = _load_data(trades_path, daily_path, report_path)

    print("[2/9] 构建品种日度序列 …")
    sym_series = _build_symbol_series(daily)

    print("[3/9] 品种分类 (A/B/C) …")
    cls_df    = _classify_symbols(trades)
    d_symbols = cls_df[cls_df["分类"] == "C"]["品种"].tolist()
    a_cnt = (cls_df["分类"] == "A").sum()
    b_cnt = (cls_df["分类"] == "B").sum()
    print(f"     A类 {a_cnt} 个 | B类 {b_cnt} 个 | C类 {len(d_symbols)} 个")

    print("[4/9] C类回撤与持续性 …")
    dd_df = _drawdown_metrics(sym_series, d_symbols)

    print("[5/9] C类周/月胜率回撤 …")
    wm_df = _weekly_monthly_stats(xl_sheets, d_symbols)

    print("[6/9] C类逐年正收益 …")
    yr_df = _annual_positive_years(xl_sheets, d_symbols)

    print("[7/9] C类月度收益集中度 …")
    conc_df = _monthly_concentration(xl_sheets, d_symbols)

    print("[8/9] 相关性 + 组合/板块统计 …")
    corr_matrix, corr_pairs, sec_corr = _correlation_analysis(sym_series, d_symbols)
    port_df = _portfolio_sector_stats(sym_series)

    print("[9/9] 手续费压力测试 + 综合评分 + 收益明细 …")
    stress_df      = _commission_stress_test(trades)
    summary_df     = _build_d_class_summary(d_symbols, dd_df, wm_df, yr_df, conc_df, stress_df)
    ann_matrix     = _annual_returns_matrix(xl_sheets)
    monthly_detail = _monthly_returns_detail(xl_sheets, d_symbols)
    monthly_ovw    = _monthly_returns_overview(xl_sheets, d_symbols)
    weekly_detail  = _weekly_returns_detail(xl_sheets, d_symbols)
    weekly_ovw     = _weekly_returns_overview(xl_sheets, d_symbols)

    sheets: dict[str, tuple] = {
        "品种分类":      (cls_df,     "品种分类（A/B/C）—— 收益质量与手续费健康度"),
        "C类综合评分":   (summary_df, "C类品种综合达标评分（12项评估标准）"),
        "回撤与持续性":  (dd_df,      "C类品种回撤周期 / 水下占比 / 连续亏损日 / 日回撤分位数"),
        "周月胜率回撤":  (wm_df,      "C类品种周/月平均胜率与最大回撤"),
        "年度正收益":    (yr_df,      "C类品种逐年收益 —— 正收益年份占比",   _write_annual_years_sheet),
        "收益集中度":    (conc_df,    "C类品种月度收益集中度（盈利年Top-3 / 亏损年Bot-3）"),
        "组合与板块":    (port_df,    "组合与各板块日/周/月胜率与回撤（等权）"),
        "品种相关性":    (corr_pairs, "C类品种两两相关系数"),
        "相关性矩阵":    (corr_matrix, "C类品种日收益相关性矩阵"),
        "板块相关性":    (sec_corr,   "板块内/板块间平均相关系数"),
        "手续费压力测试": (stress_df,  "手续费压力测试（×1.5 / ×2.0）"),
        "年度收益矩阵":   (ann_matrix, "全品种逐年收益率",                    _write_annual_matrix_sheet),
        "月度收益明细":   (monthly_detail, "C类品种月度收益明细",             _write_monthly_detail_sheet),
        "月度综合概览":   (monthly_ovw, "C类品种月度综合概览",
                           lambda ws, df, t: _write_overview_sheet(ws, df, t, is_weekly=False)),
        "周度收益明细":   (weekly_detail, "C类品种周度收益明细",              _write_weekly_detail_sheet),
        "周度综合概览":   (weekly_ovw, "C类品种周度综合概览",
                           lambda ws, df, t: _write_overview_sheet(ws, df, t, is_weekly=True)),
    }

    # ── 组合专属分析（仅在对应路径提供时生效，单策略调用时跳过） ──────────────
    if portfolio_daily_path is not None:
        try:
            lev_df = _build_leverage_df(portfolio_daily_path)
            sheets["杠杆与资金占用"] = (
                lev_df,
                "日杠杆率统计（收盘持仓名义市值 / 总分配资金）",
            )
            print("   + 杠杆与资金占用")
        except Exception as exc:
            print(f"  [WARN] 杠杆数据构建失败: {exc}")

    if strategy_daily_path is not None and portfolio_daily_path is not None:
        try:
            strat_df   = pd.read_csv(strategy_daily_path,  parse_dates=["date"])
            port_daily = pd.read_csv(portfolio_daily_path, parse_dates=["date"])

            ovw_df = _build_strat_contrib_overview(strat_df, port_daily)
            ann_df = _build_strat_contrib_pivot(strat_df, "YE")
            mon_df = _build_strat_contrib_pivot(strat_df, "ME")
            wk_df  = _build_strat_contrib_pivot(strat_df, "W-FRI")

            sheets["策略贡献_总览"] = (
                ovw_df,
                "全样本各策略收益贡献（净贡献 + 占比，口径 B）",
            )
            sheets["策略贡献_年度"] = (
                ann_df,
                "年度策略贡献矩阵（各策略当年 daily_pnl_pct 合计）",
                _write_contribution_heatmap,
            )
            sheets["策略贡献_月度"] = (
                mon_df,
                "月度策略贡献矩阵",
                _write_contribution_heatmap,
            )
            sheets["策略贡献_周度"] = (
                wk_df,
                "周度策略贡献矩阵",
                _write_contribution_heatmap,
            )
            print("   + 策略贡献_总览 / 年度 / 月度 / 周度")
        except Exception as exc:
            print(f"  [WARN] 策略贡献分析失败: {exc}")

    print("── 写出评价报告 ──────────────────────────────────────")
    _write_excel(output_path, sheets)
    for name, data in sheets.items():
        df = data[0]
        n = len(df) if isinstance(df, pd.DataFrame) else len(df.get("avg", []))
        print(f"   Sheet [{name}] → {n} 行")
    print(f"\n完成！报告已保存至：{output_path}")
