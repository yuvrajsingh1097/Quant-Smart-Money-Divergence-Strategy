"""
Implied Volatility Solver
==========================
Extracts implied volatility from market option prices using:
    1. Bisection method        — robust, always converges
    2. Newton-Raphson method   — fast, may fail for deep ITM/OTM
    3. Hybrid (default)        — Newton first, fallback to bisection

Also builds the full implied volatility surface from a strike/expiry grid.
"""

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from dataclasses import dataclass
from typing import Optional
import warnings


# ---------------------------------------------------------------------------
# Internal B-S price (avoids circular import)
# ---------------------------------------------------------------------------

def _bs_price(S, K, T, r, sigma, option_type="call") -> float:
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _vega(S, K, T, r, sigma) -> float:
    if sigma <= 0 or T <= 0:
        return 1e-10
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return S * norm.pdf(d1) * np.sqrt(T)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class IVResult:
    implied_vol: Optional[float]   # None if solver failed
    method: str                    # 'newton', 'bisection', 'hybrid'
    iterations: int
    error: float                   # |market_price - model_price|
    converged: bool


# ---------------------------------------------------------------------------
# Bisection solver
# ---------------------------------------------------------------------------

def iv_bisection(
    market_price: float,
    S: float, K: float, T: float, r: float,
    option_type: str = "call",
    tol: float = 1e-6,
    max_iter: int = 200,
) -> IVResult:
    """
    Implied vol via bisection on [sigma_low, sigma_high].
    Guaranteed to converge if a root exists in the bracket.
    """
    sigma_low, sigma_high = 1e-6, 10.0

    price_low  = _bs_price(S, K, T, r, sigma_low,  option_type) - market_price
    price_high = _bs_price(S, K, T, r, sigma_high, option_type) - market_price

    if price_low * price_high > 0:
        return IVResult(None, "bisection", 0, float("inf"), False)

    for i in range(max_iter):
        sigma_mid  = (sigma_low + sigma_high) / 2
        price_mid  = _bs_price(S, K, T, r, sigma_mid, option_type) - market_price

        if abs(price_mid) < tol:
            return IVResult(round(sigma_mid, 8), "bisection", i+1, abs(price_mid), True)

        if price_low * price_mid < 0:
            sigma_high = sigma_mid
        else:
            sigma_low  = sigma_mid
            price_low  = price_mid

    sigma_mid = (sigma_low + sigma_high) / 2
    err = abs(_bs_price(S, K, T, r, sigma_mid, option_type) - market_price)
    return IVResult(round(sigma_mid, 8), "bisection", max_iter, err, err < tol * 10)


# ---------------------------------------------------------------------------
# Newton-Raphson solver
# ---------------------------------------------------------------------------

def iv_newton(
    market_price: float,
    S: float, K: float, T: float, r: float,
    option_type: str = "call",
    sigma0: float = 0.20,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> IVResult:
    """
    Implied vol via Newton-Raphson.
    Fast convergence near ATM; may diverge for deep ITM/OTM.
    """
    sigma = sigma0

    for i in range(max_iter):
        price = _bs_price(S, K, T, r, sigma, option_type)
        v     = _vega(S, K, T, r, sigma)

        if abs(v) < 1e-10:
            return IVResult(None, "newton", i+1, float("inf"), False)

        diff  = price - market_price
        sigma = sigma - diff / v

        if sigma <= 0:
            return IVResult(None, "newton", i+1, float("inf"), False)

        if abs(diff) < tol:
            err = abs(_bs_price(S, K, T, r, sigma, option_type) - market_price)
            return IVResult(round(sigma, 8), "newton", i+1, err, True)

    err = abs(_bs_price(S, K, T, r, sigma, option_type) - market_price)
    return IVResult(round(sigma, 8) if sigma > 0 else None, "newton", max_iter, err, err < tol * 10)


# ---------------------------------------------------------------------------
# Hybrid solver (default — Newton first, bisection fallback)
# ---------------------------------------------------------------------------

def iv_solver(
    market_price: float,
    S: float, K: float, T: float, r: float,
    option_type: str = "call",
    tol: float = 1e-6,
) -> IVResult:
    """
    Hybrid IV solver: tries Newton-Raphson first for speed,
    falls back to bisection for robustness.

    Parameters
    ----------
    market_price : observed option price in the market
    S            : spot price
    K            : strike price
    T            : time to expiry (years)
    r            : risk-free rate
    option_type  : 'call' or 'put'
    tol          : convergence tolerance

    Returns
    -------
    IVResult with implied_vol, method used, iterations, error, converged flag
    """
    # Intrinsic value check
    if option_type == "call":
        intrinsic = max(S - K * np.exp(-r * T), 0)
    else:
        intrinsic = max(K * np.exp(-r * T) - S, 0)

    if market_price < intrinsic - tol:
        return IVResult(None, "hybrid", 0, float("inf"), False)

    # Try Newton first
    result = iv_newton(market_price, S, K, T, r, option_type, tol=tol)
    if result.converged and result.implied_vol is not None:
        result.method = "hybrid(newton)"
        return result

    # Fallback to bisection
    result = iv_bisection(market_price, S, K, T, r, option_type, tol=tol)
    if result.converged:
        result.method = "hybrid(bisection)"
    return result


# ---------------------------------------------------------------------------
# Implied volatility surface
# ---------------------------------------------------------------------------

def iv_surface(
    S: float,
    strikes: np.ndarray,
    expiries: np.ndarray,
    market_prices: np.ndarray,
    r: float,
    option_type: str = "call",
) -> dict:
    """
    Build full implied volatility surface from a grid of market prices.

    Parameters
    ----------
    S             : spot price
    strikes       : 1-D array of strikes  (shape: n_strikes)
    expiries      : 1-D array of expiries (shape: n_expiries)
    market_prices : 2-D array of prices   (shape: n_strikes × n_expiries)
    r             : risk-free rate
    option_type   : 'call' or 'put'

    Returns
    -------
    dict with:
        'iv'        : 2-D ndarray of implied vols (NaN where solver failed)
        'converged' : 2-D bool array
        'errors'    : 2-D ndarray of solver errors
    """
    n_K = len(strikes)
    n_T = len(expiries)

    iv_grid        = np.full((n_K, n_T), np.nan)
    converged_grid = np.zeros((n_K, n_T), dtype=bool)
    error_grid     = np.full((n_K, n_T), np.nan)

    for i, K in enumerate(strikes):
        for j, T in enumerate(expiries):
            res = iv_solver(market_prices[i, j], S, K, T, r, option_type)
            if res.converged and res.implied_vol is not None:
                iv_grid[i, j]        = res.implied_vol
                converged_grid[i, j] = True
                error_grid[i, j]     = res.error

    return {
        "iv":        iv_grid,
        "converged": converged_grid,
        "errors":    error_grid,
    }


# ---------------------------------------------------------------------------
# Synthetic market price generator (for testing / demo)
# ---------------------------------------------------------------------------

def synthetic_market_prices(
    S: float,
    strikes: np.ndarray,
    expiries: np.ndarray,
    r: float,
    base_vol: float = 0.20,
    smile: bool = True,
) -> np.ndarray:
    """
    Generate synthetic market prices with an optional vol smile.
    Useful for testing the IV surface solver without live data.

    Smile model: sigma(K) = base_vol + skew * (ln(K/S))^2
    """
    from pricing.bs_model import bs_price_vectorised

    if smile:
        K_grid = strikes[:, None]
        skew   = 0.5   # smile curvature
        vols   = base_vol + skew * (np.log(K_grid / S)) ** 2
        prices = np.zeros((len(strikes), len(expiries)))
        for i, K in enumerate(strikes):
            for j, T in enumerate(expiries):
                sigma_ij = float(vols[i, 0])
                from pricing.bs_model import BSMInputs, bs_price
                inp = BSMInputs(S=S, K=K, T=T, r=r, sigma=sigma_ij)
                prices[i, j] = bs_price(inp).price
        return prices
    else:
        return bs_price_vectorised(S, strikes, expiries, r, base_vol, "call")


# ---------------------------------------------------------------------------
# Quick demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pricing.bs_model import BSMInputs, bs_price

    print("=" * 55)
    print("Implied Volatility Solver Demo")
    print("=" * 55)

    # Generate a known market price and recover vol
    true_vol   = 0.2543
    inp        = BSMInputs(S=100, K=105, T=0.5, r=0.05, sigma=true_vol)
    mkt_price  = bs_price(inp).price

    print(f"\n  True vol    : {true_vol:.4f}")
    print(f"  Market price: ₹{mkt_price:.4f}")

    for method_fn, name in [(iv_newton, "Newton-Raphson"), (iv_bisection, "Bisection"), (iv_solver, "Hybrid")]:
        res = method_fn(mkt_price, S=100, K=105, T=0.5, r=0.05)
        status = "✓" if res.converged else "✗"
        print(f"\n  [{name}]")
        print(f"    {status} IV = {res.implied_vol:.6f}  |  iters={res.iterations}  |  error={res.error:.2e}")

    print("\n" + "=" * 55)
    print("Vol Surface Recovery (3×3 grid)")
    print("=" * 55)
    strikes  = np.array([90.0, 100.0, 110.0])
    expiries = np.array([0.25, 0.5,   1.0])
    prices   = synthetic_market_prices(100, strikes, expiries, 0.05, base_vol=0.20, smile=True)
    surf     = iv_surface(100, strikes, expiries, prices, 0.05)

    print("\n  Implied Vol Surface:")
    print(f"  {'Strike':>8} | " + " | ".join([f"T={t:.2f}" for t in expiries]))
    print("  " + "-" * 45)
    for i, K in enumerate(strikes):
        vols_row = " | ".join([f"{surf['iv'][i,j]:.4f}" for j in range(len(expiries))])
        print(f"  {K:>8.1f} | {vols_row}")

#smart money here mainly compily wiht ict concept of SMC which comapres two differnt currency pairs and helps us identify next move 
