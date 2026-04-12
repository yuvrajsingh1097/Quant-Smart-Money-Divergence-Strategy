# 🧠 Quant: Smart Money Divergence Strategy

A quantitative trading strategy that finds zones where **retail RSI divergence** is trapped by **ICT Smart Money structure (BOS/CHoCH)** — then fires a signal in the Smart Money direction with automated scoring and equity curve simulation.

![Smart Money Divergence Output](output.png)

---

## 💡 Core Concept

Retail traders use RSI divergence as a reversal signal. Smart Money knows this and uses it to their advantage:

```
LONG Signal (Retail Trapped Short):
  ┌──────────────────────────────────────────────┐
  │  RSI: Lower High (bearish divergence shows)  │  ← Retail goes SHORT
  │  Price: Higher High + BOS to upside          │  ← SMC says go LONG
  │  Result: Retail stops hunted → price pumps   │
  └──────────────────────────────────────────────┘

SHORT Signal (Retail Trapped Long):
  ┌──────────────────────────────────────────────┐
  │  RSI: Higher Low (bullish divergence shows)  │  ← Retail goes LONG
  │  Price: Lower Low + BOS to downside          │  ← SMC says go SHORT
  │  Result: Retail stops hunted → price dumps   │
  └──────────────────────────────────────────────┘
```

---

## ✅ Features

- **RSI Divergence Detection** — Bullish & Bearish with configurable sensitivity
- **Break of Structure (BOS)** — confirms Smart Money direction after the divergence
- **Swing High / Low engine** — N-bar pivot detection for structure mapping
- **Signal Scoring (0–100)** — based on divergence strength + BOS magnitude
- **Equity Curve Simulation** — fixed 1% risk, 2R target, TP/SL hit detection
- **Strategy Stats Panel** — win rate, P&L, drawdown, avg score
- Full dark-themed 4-panel chart: Price + RSI + Equity Curve + Stats

---



## 📁 Project Structure

```
smart-money-divergence/
├── smd_strategy.py    # All-in-one strategy script
├── output.png         # Sample output chart
└── README.md
```

---

## ⚙️ Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RSI_PERIOD` | 14 | RSI calculation period |
| `RSI_OB` | 65 | Overbought level |
| `RSI_OS` | 35 | Oversold level |
| `SWING_LOOKBACK` | 5 | Bars each side for pivot detection |
| `BOS_LOOKBACK` | 20 | Bars to look back for structure level |
| `MIN_DIV_RSI_DELTA` | 4.0 | Minimum RSI gap to qualify as divergence |
| `MIN_BOS_PIPS` | 4 | Minimum BOS size in pips |
| `RISK_PCT` | 0.01 | Risk per trade (1%) |
| `RR` | 2.0 | Reward:Risk ratio |
| `STARTING_EQUITY` | 10,000 | Starting account size (USD) |

---

## 📊 Signal Scoring Formula

```
Score = 50 + (divergence_rsi_gap × 2) + (bos_magnitude_pips × 0.5)
Score is capped at 100
```

Higher score = stronger confluence between retail trap and SMC confirmation.

---

## 🔌 Use with Real Data

```python
import yfinance as yf
df = yf.download("EURUSD=X", period="60d", interval="1h")
df.columns = [c.lower() for c in df.columns]
```

---

## 📚 ICT + Quant Concepts Used

| Concept | Source | Role |
|---|---|---|
| RSI Divergence | Traditional TA | Retail trap detector |
| Break of Structure (BOS) | ICT | Smart Money confirmation |
| Swing High / Low | ICT / Quant | Structure mapping |
| Signal Scoring | Quant | Confluence ranking |
| Equity Simulation | Quant | Strategy validation |

---

## 🛠 Requirements

- Python 3.8+
- pandas · numpy · matplotlib · scipy

---

