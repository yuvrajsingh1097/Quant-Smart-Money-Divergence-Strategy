"""
Quant: Smart Money Divergence Strategy
=======================================
Finds zones where RETAIL indicators (RSI) show divergence
while ICT STRUCTURE (BOS / CHoCH) confirms Smart Money direction.

Logic:
  LONG  signal : RSI shows Bearish Divergence (retail shorts) BUT
                 price makes a Break of Structure to the UPSIDE (SMC confirms long)
                 → Retail trapped short, Smart Money going long

  SHORT signal : RSI shows Bullish Divergence (retail longs) BUT
                 price makes a Break of Structure to the DOWNSIDE (SMC confirms short)
                 → Retail trapped long, Smart Money going short

Quant layer:
  - Signal scoring (0–100) based on divergence strength + BOS magnitude
  - Rolling win-rate tracker
  - Equity curve simulation with fixed 1% risk, 2R target, 1R stop

Author : Your Name
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
import warnings
warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────
RSI_PERIOD         = 14
RSI_OB             = 65        # overbought threshold
RSI_OS             = 35        # oversold threshold
SWING_LOOKBACK     = 5         # bars each side for swing detection
BOS_LOOKBACK       = 20        # bars to look back for structure level
MIN_DIV_RSI_DELTA  = 4.0       # minimum RSI divergence gap (points)
MIN_BOS_PIPS       = 4         # minimum BOS size in pips
PIP                = 0.0001
RISK_PCT           = 0.01      # 1% risk per trade
RR                 = 2.0       # reward:risk ratio
STARTING_EQUITY    = 10_000

# ──────────────────────────────────────────────
#  1. DATA GENERATION
# ──────────────────────────────────────────────
def generate_data(n=400, seed=21):
    np.random.seed(seed)
    price = 1.0900
    closes = [price]

    for i in range(n - 1):
        # Trending + mean-reverting mix
        trend  = np.sin(i / 40) * 0.0003
        noise  = np.random.normal(0, 0.0011)
        closes.append(round(closes[-1] + trend + noise, 5))

    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    df = pd.DataFrame(index=dates)
    df["close"] = closes
    df["open"]  = df["close"].shift(1).bfill()
    df["high"]  = df[["open", "close"]].max(axis=1) + abs(np.random.normal(0, 0.0005, n))
    df["low"]   = df[["open", "close"]].min(axis=1) - abs(np.random.normal(0, 0.0005, n))
    df["high"]  = df["high"].round(5)
    df["low"]   = df["low"].round(5)
    return df


# ──────────────────────────────────────────────
#  2. RSI
# ──────────────────────────────────────────────
def compute_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ──────────────────────────────────────────────
#  3. SWING HIGHS / LOWS
# ──────────────────────────────────────────────
def find_swings(df, n=5):
    """Return boolean Series for swing highs and swing lows."""
    sh = pd.Series(False, index=df.index)
    sl = pd.Series(False, index=df.index)

    for i in range(n, len(df) - n):
        window_h = df["high"].iloc[i - n: i + n + 1]
        window_l = df["low"].iloc[i - n: i + n + 1]
        if df["high"].iloc[i] == window_h.max():
            sh.iloc[i] = True
        if df["low"].iloc[i] == window_l.min():
            sl.iloc[i] = True

    return sh, sl


# ──────────────────────────────────────────────
#  4. BREAK OF STRUCTURE DETECTION
# ──────────────────────────────────────────────
def detect_bos(df, swing_highs, swing_lows, lookback=20):
    """
    Bullish BOS : close breaks ABOVE the most recent swing high
    Bearish BOS : close breaks BELOW the most recent swing low
    """
    bull_bos = pd.Series(np.nan, index=df.index)
    bear_bos = pd.Series(np.nan, index=df.index)
    bull_level = pd.Series(np.nan, index=df.index)
    bear_level = pd.Series(np.nan, index=df.index)

    for i in range(lookback, len(df)):
        window    = df.iloc[i - lookback: i]
        sh_window = swing_highs.iloc[i - lookback: i]
        sl_window = swing_lows.iloc[i - lookback: i]

        recent_sh = window["high"][sh_window].max() if sh_window.any() else np.nan
        recent_sl = window["low"][sl_window].min()  if sl_window.any() else np.nan

        close = df["close"].iloc[i]

        if not np.isnan(recent_sh) and close > recent_sh + MIN_BOS_PIPS * PIP:
            bull_bos.iloc[i]   = close
            bull_level.iloc[i] = recent_sh

        if not np.isnan(recent_sl) and close < recent_sl - MIN_BOS_PIPS * PIP:
            bear_bos.iloc[i]   = close
            bear_level.iloc[i] = recent_sl

    return bull_bos, bear_bos, bull_level, bear_level


# ──────────────────────────────────────────────
#  5. DIVERGENCE DETECTION
# ──────────────────────────────────────────────
def detect_divergence(df, rsi, swing_highs, swing_lows, lookback=30):
    """
    Bearish Divergence : price makes Higher High BUT RSI makes Lower High
    Bullish Divergence : price makes Lower Low  BUT RSI makes Higher Low
    """
    bear_div = pd.Series(False, index=df.index)
    bull_div = pd.Series(False, index=df.index)
    div_strength = pd.Series(0.0, index=df.index)

    sh_idx = df.index[swing_highs]
    sl_idx = df.index[swing_lows]

    # Bearish divergence at swing highs
    for k in range(1, len(sh_idx)):
        i2 = sh_idx[k]
        # find previous swing high within lookback
        prev = [x for x in sh_idx[:k] if (df.index.get_loc(i2) - df.index.get_loc(x)) <= lookback]
        if not prev:
            continue
        i1 = prev[-1]
        price_hh = df.loc[i2, "high"] > df.loc[i1, "high"]
        rsi_lh   = rsi.loc[i2] < rsi.loc[i1]
        rsi_gap  = rsi.loc[i1] - rsi.loc[i2]
        if price_hh and rsi_lh and rsi_gap >= MIN_DIV_RSI_DELTA:
            bear_div.loc[i2]    = True
            div_strength.loc[i2] = round(rsi_gap, 1)

    # Bullish divergence at swing lows
    for k in range(1, len(sl_idx)):
        i2 = sl_idx[k]
        prev = [x for x in sl_idx[:k] if (df.index.get_loc(i2) - df.index.get_loc(x)) <= lookback]
        if not prev:
            continue
        i1 = prev[-1]
        price_ll = df.loc[i2, "low"] < df.loc[i1, "low"]
        rsi_hl   = rsi.loc[i2] > rsi.loc[i1]
        rsi_gap  = rsi.loc[i2] - rsi.loc[i1]
        if price_ll and rsi_hl and rsi_gap >= MIN_DIV_RSI_DELTA:
            bull_div.loc[i2]    = True
            div_strength.loc[i2] = round(rsi_gap, 1)

    return bull_div, bear_div, div_strength


# ──────────────────────────────────────────────
#  6. COMBINE → SIGNALS
# ──────────────────────────────────────────────
def generate_signals(df, bull_div, bear_div, bull_bos, bear_bos,
                     div_strength, bull_level, bear_level):
    """
    LONG  : recent bullish divergence + bullish BOS within next 8 bars
    SHORT : recent bearish divergence + bearish BOS within next 8 bars
    """
    signals = []
    window  = 8

    bull_div_idx = set(df.index[bull_div])
    bear_div_idx = set(df.index[bear_div])

    for i in range(len(df)):
        ts    = df.index[i]
        close = df["close"].iloc[i]

        # Check for recent bull div in past `window` bars
        recent_bull_div = any(
            df.index[j] in bull_div_idx
            for j in range(max(0, i - window), i)
        )
        recent_bear_div = any(
            df.index[j] in bear_div_idx
            for j in range(max(0, i - window), i)
        )

        if recent_bull_div and not np.isnan(bull_bos.iloc[i]):
            # Divergence strength for scoring
            ds = max(
                div_strength.iloc[max(0, i - window): i].max(), 0.1
            )
            bos_mag = (close - bull_level.iloc[i]) / PIP if not np.isnan(bull_level.iloc[i]) else 0
            score = min(100, round(50 + ds * 2 + bos_mag * 0.5))
            sl    = close - (close * 0.0020)
            tp    = close + (close - sl) * RR
            signals.append({
                "time": ts, "type": "LONG", "price": close,
                "sl": round(sl, 5), "tp": round(tp, 5),
                "score": score, "div_strength": ds,
                "bos_mag": round(bos_mag, 1)
            })

        elif recent_bear_div and not np.isnan(bear_bos.iloc[i]):
            ds = max(
                div_strength.iloc[max(0, i - window): i].max(), 0.1
            )
            bos_mag = (bear_level.iloc[i] - close) / PIP if not np.isnan(bear_level.iloc[i]) else 0
            score = min(100, round(50 + ds * 2 + bos_mag * 0.5))
            sl    = close + (close * 0.0020)
            tp    = close - (sl - close) * RR
            signals.append({
                "time": ts, "type": "SHORT", "price": close,
                "sl": round(sl, 5), "tp": round(tp, 5),
                "score": score, "div_strength": ds,
                "bos_mag": round(bos_mag, 1)
            })

    return pd.DataFrame(signals)


# ──────────────────────────────────────────────
#  7. EQUITY CURVE SIMULATION
# ──────────────────────────────────────────────
def simulate_equity(df, signals_df, equity=STARTING_EQUITY):
    if signals_df.empty:
        return pd.Series([equity], index=[df.index[0]])

    equity_curve = [equity]
    times        = [df.index[0]]
    results      = []

    for _, sig in signals_df.iterrows():
        sig_i  = df.index.get_loc(sig["time"])
        risk   = equity * RISK_PCT
        sl_pips = abs(sig["price"] - sig["sl"]) / PIP
        tp_pips = abs(sig["tp"]    - sig["price"]) / PIP

        hit = None
        for j in range(sig_i + 1, min(sig_i + 60, len(df))):
            h = df["high"].iloc[j]
            l = df["low"].iloc[j]
            if sig["type"] == "LONG":
                if l <= sig["sl"]:  hit = "SL"; break
                if h >= sig["tp"]:  hit = "TP"; break
            else:
                if h >= sig["sl"]:  hit = "SL"; break
                if l <= sig["tp"]:  hit = "TP"; break

        if hit == "TP":
            pnl = risk * RR
        elif hit == "SL":
            pnl = -risk
        else:
            pnl = 0   # open / time-out

        equity += pnl
        equity_curve.append(equity)
        times.append(sig["time"])
        results.append(hit)

    signals_df = signals_df.copy()
    signals_df["result"] = results
    return pd.Series(equity_curve, index=times), signals_df


# ──────────────────────────────────────────────
#  8. PLOT
# ──────────────────────────────────────────────
def plot_all(df, rsi, signals_df, bull_div, bear_div,
             swing_highs, swing_lows, equity_curve):

    PLOT_N = 200
    df_p   = df.iloc[-PLOT_N:]
    rsi_p  = rsi.iloc[-PLOT_N:]
    sig_p  = signals_df[signals_df["time"] >= df_p.index[0]] if not signals_df.empty else pd.DataFrame()

    fig = plt.figure(figsize=(20, 13))
    fig.patch.set_facecolor("#0d1117")
    gs  = gridspec.GridSpec(3, 2,
                            height_ratios=[3, 1.2, 1.5],
                            hspace=0.35, wspace=0.28)

    ax_price  = fig.add_subplot(gs[0, :])
    ax_rsi    = fig.add_subplot(gs[1, :], sharex=ax_price)
    ax_equity = fig.add_subplot(gs[2, 0])
    ax_stats  = fig.add_subplot(gs[2, 1])

    for ax in [ax_price, ax_rsi, ax_equity, ax_stats]:
        ax.set_facecolor("#0d1117")
        for sp in ax.spines.values():
            sp.set_edgecolor("#30363d")
        ax.tick_params(colors="#8b949e", labelsize=8)

    x_map = {ts: i for i, ts in enumerate(df_p.index)}
    xs    = np.arange(len(df_p))

    # ── Candlesticks ──
    for i, (ts, row) in enumerate(df_p.iterrows()):
        bull = row["close"] >= row["open"]
        col  = "#26a69a" if bull else "#ef5350"
        wk   = "#1a7a74" if bull else "#b03030"
        ax_price.plot([i, i], [row["low"], row["high"]], color=wk, lw=0.8, zorder=2)
        bot = min(row["open"], row["close"])
        h   = max(abs(row["close"] - row["open"]), 0.000025)
        ax_price.add_patch(mpatches.FancyBboxPatch(
            (i - 0.3, bot), 0.6, h,
            boxstyle="square,pad=0", color=col, zorder=3))

    # ── Swing markers ──
    for ts in df_p.index[swing_highs[df_p.index]]:
        xi = x_map[ts]
        ax_price.scatter(xi, df_p.loc[ts, "high"] + 0.00015,
                         marker="v", color="#f0a040", s=40, zorder=5)

    for ts in df_p.index[swing_lows[df_p.index]]:
        xi = x_map[ts]
        ax_price.scatter(xi, df_p.loc[ts, "low"] - 0.00015,
                         marker="^", color="#5090d0", s=40, zorder=5)

    # ── Divergence markers ──
    bull_div_p = bull_div[df_p.index]
    bear_div_p = bear_div[df_p.index]

    for ts in df_p.index[bull_div_p]:
        xi = x_map[ts]
        ax_price.annotate("BULL DIV", xy=(xi, df_p.loc[ts, "low"] - 0.00025),
                          color="#00e676", fontsize=6.5, ha="center", fontweight="bold",
                          bbox=dict(boxstyle="round,pad=0.2", fc="#003320", ec="#00e676", lw=0.8))

    for ts in df_p.index[bear_div_p]:
        xi = x_map[ts]
        ax_price.annotate("BEAR DIV", xy=(xi, df_p.loc[ts, "high"] + 0.00020),
                          color="#ff5252", fontsize=6.5, ha="center", fontweight="bold",
                          bbox=dict(boxstyle="round,pad=0.2", fc="#330000", ec="#ff5252", lw=0.8))

    # ── Signal arrows ──
    for _, sig in sig_p.iterrows():
        xi = x_map.get(sig["time"])
        if xi is None:
            continue
        is_long = sig["type"] == "LONG"
        color   = "#00e676" if is_long else "#ff5252"
        marker  = "^" if is_long else "v"
        y_pos   = sig["price"] - 0.0004 if is_long else sig["price"] + 0.0004
        ax_price.scatter(xi, y_pos, marker=marker, color=color, s=120, zorder=7)
        ax_price.text(xi, y_pos - 0.0003 if is_long else y_pos + 0.0002,
                      f"#{sig['score']}",
                      color=color, fontsize=6.5, ha="center", fontweight="bold")

    ax_price.set_title("Smart Money Divergence Strategy  —  EUR/USD H1",
                       color="#e6edf3", fontsize=13, fontweight="bold", pad=10)
    ax_price.set_ylabel("Price", color="#8b949e", fontsize=9)
    ax_price.yaxis.set_major_formatter(plt.FormatStrFormatter("%.4f"))
    ax_price.grid(color="#21262d", ls="--", lw=0.5)
    ax_price.tick_params(labelbottom=False)

    # ── RSI panel ──
    ax_rsi.plot(xs, rsi_p.values, color="#7c8cf8", lw=1.3, zorder=3)
    ax_rsi.axhline(RSI_OB, color="#ef5350", lw=0.8, ls="--", alpha=0.7)
    ax_rsi.axhline(RSI_OS, color="#26a69a", lw=0.8, ls="--", alpha=0.7)
    ax_rsi.axhline(50,     color="#8b949e", lw=0.5, ls=":",  alpha=0.5)
    ax_rsi.fill_between(xs, rsi_p.values, RSI_OB,
                        where=rsi_p.values >= RSI_OB,
                        color="#ef5350", alpha=0.15)
    ax_rsi.fill_between(xs, rsi_p.values, RSI_OS,
                        where=rsi_p.values <= RSI_OS,
                        color="#26a69a", alpha=0.15)

    # RSI divergence dots
    for ts in df_p.index[bull_div_p]:
        xi = x_map[ts]
        ax_rsi.scatter(xi, rsi_p.loc[ts], color="#00e676", s=50, zorder=5)
    for ts in df_p.index[bear_div_p]:
        xi = x_map[ts]
        ax_rsi.scatter(xi, rsi_p.loc[ts], color="#ff5252", s=50, zorder=5)

    ax_rsi.set_ylabel("RSI", color="#8b949e", fontsize=9)
    ax_rsi.set_ylim(0, 100)
    ax_rsi.grid(color="#21262d", ls="--", lw=0.5)

    tick_step = max(1, PLOT_N // 10)
    xticks  = xs[::tick_step]
    xlabels = [df_p.index[i].strftime("%m/%d %H:%M") for i in xticks]
    ax_rsi.set_xticks(xticks)
    ax_rsi.set_xticklabels(xlabels, rotation=30, ha="right", color="#8b949e", fontsize=7)

    # ── Equity curve ──
    eq_vals = equity_curve.values
    eq_xs   = np.arange(len(eq_vals))
    ax_equity.plot(eq_xs, eq_vals, color="#7c8cf8", lw=2, zorder=3)
    ax_equity.fill_between(eq_xs, STARTING_EQUITY, eq_vals,
                           where=eq_vals >= STARTING_EQUITY,
                           color="#26a69a", alpha=0.2)
    ax_equity.fill_between(eq_xs, STARTING_EQUITY, eq_vals,
                           where=eq_vals < STARTING_EQUITY,
                           color="#ef5350", alpha=0.2)
    ax_equity.axhline(STARTING_EQUITY, color="#8b949e", lw=0.8, ls="--")
    ax_equity.set_title("Equity Curve", color="#e6edf3", fontsize=10, fontweight="bold")
    ax_equity.set_ylabel("USD", color="#8b949e", fontsize=8)
    ax_equity.yaxis.set_major_formatter(plt.FormatStrFormatter("$%.0f"))
    ax_equity.grid(color="#21262d", ls="--", lw=0.5)
    final_eq = eq_vals[-1]
    pnl      = final_eq - STARTING_EQUITY
    color_eq  = "#26a69a" if pnl >= 0 else "#ef5350"
    ax_equity.text(len(eq_xs) - 1, final_eq,
                   f"  ${final_eq:,.0f}", color=color_eq,
                   fontsize=8, va="center", fontweight="bold")

    # ── Stats panel ──
    ax_stats.axis("off")
    if not signals_df.empty and "result" in signals_df.columns:
        res   = signals_df["result"].dropna()
        total = len(res)
        wins  = (res == "TP").sum()
        loss  = (res == "SL").sum()
        wr    = wins / total * 100 if total > 0 else 0
        avg_score = signals_df["score"].mean()
        net_pnl   = final_eq - STARTING_EQUITY
        max_eq    = max(eq_vals)
        min_eq    = min(eq_vals)
        dd        = (max_eq - min_eq) / max_eq * 100

        lines = [
            ("Strategy", "SM Divergence"),
            ("Instrument", "EUR/USD H1"),
            ("", ""),
            ("Total Signals", str(total)),
            ("Winners (TP)", f"{wins}  ({wr:.1f}%)"),
            ("Losers  (SL)", f"{loss}"),
            ("Avg Signal Score", f"{avg_score:.0f} / 100"),
            ("", ""),
            ("Starting Equity", f"${STARTING_EQUITY:,}"),
            ("Final Equity", f"${final_eq:,.0f}"),
            ("Net P&L", f"${net_pnl:+,.0f}"),
            ("Max Drawdown", f"{dd:.1f}%"),
            ("Risk per Trade", f"{RISK_PCT*100:.0f}%"),
            ("Reward:Risk", f"{RR:.1f}R"),
        ]
        for row_i, (k, v) in enumerate(lines):
            y = 0.97 - row_i * 0.068
            if k == "":
                continue
            color_v = "#e6edf3"
            if k == "Net P&L":
                color_v = "#26a69a" if net_pnl >= 0 else "#ef5350"
            ax_stats.text(0.02, y, k,   color="#8b949e",  fontsize=8.5, transform=ax_stats.transAxes)
            ax_stats.text(0.55, y, v,   color=color_v,   fontsize=8.5, transform=ax_stats.transAxes,
                          fontweight="bold")

    ax_stats.set_title("Strategy Stats", color="#e6edf3", fontsize=10, fontweight="bold")
    ax_stats.add_patch(mpatches.FancyBboxPatch(
        (0, 0), 1, 1, transform=ax_stats.transAxes,
        boxstyle="round,pad=0.02", fc="#161b22", ec="#30363d", lw=1, zorder=0
    ))

    # ── Legend ──
    handles = [
        mlines.Line2D([], [], color="#00e676", marker="^", ls="None", label="LONG Signal"),
        mlines.Line2D([], [], color="#ff5252", marker="v", ls="None", label="SHORT Signal"),
        mpatches.Patch(color="#00e676", alpha=0.4, label="Bullish Divergence"),
        mpatches.Patch(color="#ff5252", alpha=0.4, label="Bearish Divergence"),
        mlines.Line2D([], [], color="#f0a040", marker="v", ls="None", label="Swing High"),
        mlines.Line2D([], [], color="#5090d0", marker="^", ls="None", label="Swing Low"),
    ]
    ax_price.legend(handles=handles, facecolor="#161b22", edgecolor="#30363d",
                    labelcolor="#e6edf3", fontsize=8, loc="upper left", ncol=3)

    plt.savefig("output.png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.show()
    print("✅  Chart saved → output.png")


# ──────────────────────────────────────────────
#  CONSOLE SUMMARY
# ──────────────────────────────────────────────
def print_summary(signals_df):
    print("\n" + "=" * 60)
    print("  Quant Smart Money Divergence — Signal Log")
    print("=" * 60)
    if signals_df.empty:
        print("  No signals found.")
        return
    total = len(signals_df)
    print(f"  Total signals : {total}")
    if "result" in signals_df.columns:
        res  = signals_df["result"].dropna()
        wins = (res == "TP").sum()
        loss = (res == "SL").sum()
        wr   = wins / len(res) * 100 if len(res) > 0 else 0
        print(f"  Win rate      : {wr:.1f}%  ({wins}W / {loss}L)")
        print(f"  Avg score     : {signals_df['score'].mean():.1f} / 100")
    print()
    cols = ["time", "type", "price", "sl", "tp", "score", "div_strength"]
    if "result" in signals_df.columns:
        cols.append("result")
    print(signals_df[cols].to_string(index=False))
    print("=" * 60)


# ──────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("📊  Generating EUR/USD H1 data ...")
    df = generate_data(n=400, seed=32)

    print("📐  Computing RSI & Swings ...")
    rsi = compute_rsi(df["close"], RSI_PERIOD)
    swing_highs, swing_lows = find_swings(df, SWING_LOOKBACK)

    print("🏗️   Detecting Break of Structure ...")
    bull_bos, bear_bos, bull_level, bear_level = detect_bos(
        df, swing_highs, swing_lows, BOS_LOOKBACK)

    print("📉  Detecting Divergences ...")
    bull_div, bear_div, div_strength = detect_divergence(
        df, rsi, swing_highs, swing_lows)

    print("⚡  Generating Smart Money Divergence Signals ...")
    signals_df = generate_signals(
        df, bull_div, bear_div, bull_bos, bear_bos,
        div_strength, bull_level, bear_level)

    print("💰  Simulating Equity Curve ...")
    equity_curve, signals_df = simulate_equity(df, signals_df)

    print_summary(signals_df)

    print("\n🎨  Plotting ...")
    plot_all(df, rsi, signals_df, bull_div, bear_div,
             swing_highs, swing_lows, equity_curve)