"""Germany / Global universe helpers.

Seeded DAX + MDAX constituents and a small global large-cap set so the
workflow is usable offline. Replace with a live fetcher (Xetra / Wikipedia /
@fin.cx/opendata) for production use.
"""

from __future__ import annotations

# DAX 40 - Xetra symbols (yfinance ".DE" suffix added at use-site).
DAX_SEED: list[tuple[str, str, str]] = [
    ("SAP", "SAP", "Information Technology"),
    ("SIE", "Siemens", "Industrials"),
    ("ALV", "Allianz", "Financials"),
    ("DTE", "Deutsche Telekom", "Communication Services"),
    ("AIR", "Airbus", "Industrials"),
    ("MUV2", "Munich Re", "Financials"),
    ("MBG", "Mercedes-Benz Group", "Consumer Discretionary"),
    ("BMW", "BMW", "Consumer Discretionary"),
    ("VOW3", "Volkswagen Pref", "Consumer Discretionary"),
    ("BAS", "BASF", "Materials"),
    ("BAYN", "Bayer", "Health Care"),
    ("DBK", "Deutsche Bank", "Financials"),
    ("DB1", "Deutsche Boerse", "Financials"),
    ("ADS", "Adidas", "Consumer Discretionary"),
    ("BEI", "Beiersdorf", "Consumer Staples"),
    ("HEN3", "Henkel Pref", "Consumer Staples"),
    ("HEI", "HeidelbergCement", "Materials"),
    ("IFX", "Infineon", "Information Technology"),
    ("MRK", "Merck KGaA", "Health Care"),
    ("RWE", "RWE", "Utilities"),
    ("EOAN", "E.ON", "Utilities"),
    ("CON", "Continental", "Consumer Discretionary"),
    ("FRE", "Fresenius", "Health Care"),
    ("FME", "Fresenius Medical Care", "Health Care"),
    ("DPW", "Deutsche Post / DHL", "Industrials"),
    ("BNR", "Brenntag", "Industrials"),
    ("SY1", "Symrise", "Materials"),
    ("MTX", "MTU Aero Engines", "Industrials"),
    ("SHL", "Siemens Healthineers", "Health Care"),
    ("SRT3", "Sartorius Pref", "Health Care"),
    ("ZAL", "Zalando", "Consumer Discretionary"),
    ("HNR1", "Hannover Rueck", "Financials"),
    ("PAH3", "Porsche Automobil Holding", "Consumer Discretionary"),
    ("P911", "Porsche AG", "Consumer Discretionary"),
    ("RHM", "Rheinmetall", "Industrials"),
    ("CBK", "Commerzbank", "Financials"),
    ("ENR", "Siemens Energy", "Industrials"),
    ("VNA", "Vonovia", "Real Estate"),
    ("QIA", "Qiagen", "Health Care"),
]

GLOBAL_LARGE_SEED: list[tuple[str, str, str]] = [
    ("AAPL", "Apple", "Information Technology"),
    ("MSFT", "Microsoft", "Information Technology"),
    ("GOOGL", "Alphabet", "Communication Services"),
    ("AMZN", "Amazon", "Consumer Discretionary"),
    ("NVDA", "NVIDIA", "Information Technology"),
    ("META", "Meta Platforms", "Communication Services"),
    ("TSLA", "Tesla", "Consumer Discretionary"),
    ("BRK-B", "Berkshire Hathaway B", "Financials"),
    ("JPM", "JPMorgan Chase", "Financials"),
    ("V", "Visa", "Financials"),
    ("MA", "Mastercard", "Financials"),
    ("UNH", "UnitedHealth", "Health Care"),
    ("LLY", "Eli Lilly", "Health Care"),
    ("XOM", "ExxonMobil", "Energy"),
    ("KO", "Coca-Cola", "Consumer Staples"),
    ("PEP", "PepsiCo", "Consumer Staples"),
    ("WMT", "Walmart", "Consumer Staples"),
    ("PG", "Procter & Gamble", "Consumer Staples"),
    ("ASML", "ASML Holding", "Information Technology"),
    ("NVO", "Novo Nordisk", "Health Care"),
]


def get_constituents(universe: str) -> list[tuple[str, str, str]]:
    """Return list of (symbol, name, sector) for a named universe."""
    u = (universe or "").upper()
    if u == "DAX":
        return list(DAX_SEED)
    if u in {"DAX_PLUS_MDAX", "MDAX"}:
        # No separate MDAX seed - we return DAX as the working subset.
        return list(DAX_SEED)
    if u == "GLOBAL_LARGE":
        return list(GLOBAL_LARGE_SEED)
    if u == "EURO_STOXX_50":
        # Subset of DAX is a usable proxy for offline mode.
        return list(DAX_SEED)
    return list(DAX_SEED)
