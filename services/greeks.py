import math
from scipy.stats import norm

def calculate_greeks(option_type: str, S: float, K: float, T: float, r: float, sigma: float):
    """
    Calculate option greeks: Delta, Gamma, Vega, Theta using Black-Scholes

    Parameters:
    - option_type: 'call' or 'put'
    - S: Spot price
    - K: Strike price
    - T: Time to expiration in years
    - r: Risk-free rate (annual, decimal, e.g., 0.05)
    - sigma: Implied volatility (decimal, e.g., 0.25)

    Returns:
    - Dictionary with Delta, Gamma, Vega, Theta
    """

    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}

    d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type.lower() == 'call':
        delta = norm.cdf(d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * math.sqrt(T))) - r * K * math.exp(-r * T) * norm.cdf(d2)
    else:
        delta = -norm.cdf(-d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * math.sqrt(T))) + r * K * math.exp(-r * T) * norm.cdf(-d2)

    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * norm.pdf(d1) * math.sqrt(T)

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega / 100,   # per 1% change in vol
        "theta": theta / 365  # per day
    }
