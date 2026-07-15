"""India universe helpers (NSE).

We embed a static, hand-curated subset of NIFTY50 + popular large caps to keep
the project working completely offline. Replace with a live constituents
fetcher (NSE CSV / finstack-mcp / india-stock-mcp) for production use.
"""

from __future__ import annotations

# (NSE symbol, company name, GICS-ish sector)
NIFTY50_SEED: list[tuple[str, str, str]] = [
    ("RELIANCE", "Reliance Industries", "Energy"),
    ("TCS", "Tata Consultancy Services", "Information Technology"),
    ("HDFCBANK", "HDFC Bank", "Financials"),
    ("INFY", "Infosys", "Information Technology"),
    ("ICICIBANK", "ICICI Bank", "Financials"),
    ("HINDUNILVR", "Hindustan Unilever", "Consumer Staples"),
    ("ITC", "ITC", "Consumer Staples"),
    ("LT", "Larsen & Toubro", "Industrials"),
    ("SBIN", "State Bank of India", "Financials"),
    ("BHARTIARTL", "Bharti Airtel", "Communication Services"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Financials"),
    ("AXISBANK", "Axis Bank", "Financials"),
    ("ASIANPAINT", "Asian Paints", "Materials"),
    ("MARUTI", "Maruti Suzuki", "Consumer Discretionary"),
    ("TITAN", "Titan Company", "Consumer Discretionary"),
    ("SUNPHARMA", "Sun Pharmaceutical", "Health Care"),
    ("BAJFINANCE", "Bajaj Finance", "Financials"),
    ("HCLTECH", "HCL Technologies", "Information Technology"),
    ("WIPRO", "Wipro", "Information Technology"),
    ("ONGC", "ONGC", "Energy"),
    ("NTPC", "NTPC", "Utilities"),
    ("POWERGRID", "Power Grid Corporation", "Utilities"),
    ("TATAMOTORS", "Tata Motors", "Consumer Discretionary"),
    ("ULTRACEMCO", "UltraTech Cement", "Materials"),
    ("M&M", "Mahindra & Mahindra", "Consumer Discretionary"),
    ("NESTLEIND", "Nestle India", "Consumer Staples"),
    ("ADANIENT", "Adani Enterprises", "Industrials"),
    ("ADANIPORTS", "Adani Ports", "Industrials"),
    ("JSWSTEEL", "JSW Steel", "Materials"),
    ("TATASTEEL", "Tata Steel", "Materials"),
    ("INDUSINDBK", "IndusInd Bank", "Financials"),
    ("BAJAJFINSV", "Bajaj Finserv", "Financials"),
    ("DRREDDY", "Dr Reddy's Laboratories", "Health Care"),
    ("CIPLA", "Cipla", "Health Care"),
    ("GRASIM", "Grasim Industries", "Materials"),
    ("BRITANNIA", "Britannia Industries", "Consumer Staples"),
    ("DIVISLAB", "Divi's Laboratories", "Health Care"),
    ("APOLLOHOSP", "Apollo Hospitals", "Health Care"),
    ("HEROMOTOCO", "Hero MotoCorp", "Consumer Discretionary"),
    ("EICHERMOT", "Eicher Motors", "Consumer Discretionary"),
    ("HDFCLIFE", "HDFC Life Insurance", "Financials"),
    ("SBILIFE", "SBI Life Insurance", "Financials"),
    ("BPCL", "Bharat Petroleum", "Energy"),
    ("COALINDIA", "Coal India", "Energy"),
    ("TECHM", "Tech Mahindra", "Information Technology"),
    ("LTIM", "LTIMindtree", "Information Technology"),
    ("TATACONSUM", "Tata Consumer Products", "Consumer Staples"),
    ("BAJAJ-AUTO", "Bajaj Auto", "Consumer Discretionary"),
    ("UPL", "UPL", "Materials"),
    ("SHRIRAMFIN", "Shriram Finance", "Financials"),
]


def get_constituents(universe: str) -> list[tuple[str, str, str]]:
    """Return list of (symbol, name, sector). Symbols are bare NSE codes
    (no .NS suffix); the caller adds the yahoo suffix from the profile.
    """
    universe = (universe or "").upper()
    if universe in {"NIFTY50", "NIFTY500", "BSE500"}:
        # We only seed NIFTY50; broader indices still use the seed list as a
        # working subset until a live fetcher is wired in.
        return list(NIFTY50_SEED)
    return list(NIFTY50_SEED)
