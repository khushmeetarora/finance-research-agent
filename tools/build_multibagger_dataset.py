#!/usr/bin/env python
"""Build a LABELED, price-VERIFIED multibagger vs non-multibagger dataset.

This is a *standalone* data-engineering builder for FRA V2 (docs/FRA_V2_DATASET.md).
It does NOT import or modify any FRA source code. It only:

  1. Holds a curated candidate universe (winners + controls) discovered from
     reputable FREE writeups (Motilal Oswal Wealth Creation Studies, BusinessToday,
     stockpricearchive, Rediff PSU-laggard reports, etc. -- see DISCOVERY sources
     per row). The web is used ONLY for candidate *discovery*.
  2. Pulls split/dividend-adjusted price history from yfinance (free) and
     computes the realized 3y / 5y forward multiple and the peak multiple inside
     the 5-year window from the *actual pulled prices* -- never from web claims.
  3. Assigns a reproducible label from those verified multiples.

Labels (winner labels use the PEAK multiple reached inside the <=5y window;
control/intermediate use the REALIZED 5-year multiple -- see docs for rationale):
  * multibagger_strong  peak_mult_5y >= 5.0                      (was a >=5-bagger)
  * multibagger         3.0 <= peak_mult_5y < 5.0                (was a >=3-bagger)
  * intermediate        peak_mult_5y < 3.0 AND mult_5y >= 1.5    (solid but not a 3-bagger)
  * non_multibagger     peak_mult_5y < 3.0 AND mult_5y <  1.5    (control; survived, did not multiply)
  * unlabeled_partial   window incomplete AND peak never reached 3x (can't confirm)

Using the realized 5y multiple for the control cut correctly classifies names
that had a transient pop and then collapsed (e.g. a fraud that ticked to ~2x
then went to ~0) as non_multibagger rather than "intermediate".

Prices are auto-adjusted (splits + dividends), so multiples are total-return-ish.

Idempotent: per-symbol raw history is cached under data/_price_cache/. Re-running
reproduces the same CSV. Use --refresh to force a re-pull from yfinance.

Usage (Windows / conda env `fra`):
    conda run -n fra python tools/build_multibagger_dataset.py
    conda run -n fra python tools/build_multibagger_dataset.py --refresh
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import warnings
from datetime import date, datetime, timedelta

warnings.filterwarnings("ignore")

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_DATA = os.path.join(_ROOT, "data")
_CACHE = os.path.join(_DATA, "_price_cache")
_OUT_CSV = os.path.join(_DATA, "multibagger_dataset.csv")

# --------------------------------------------------------------------------
# Label thresholds (documented in docs/FRA_V2_DATASET.md)
# --------------------------------------------------------------------------
STRONG_X = 5.0
MULTI_X = 3.0
CONTROL_X = 1.5
DATE_TOL_DAYS = 20     # nearest trading day tolerance around a target date
MIN_FWD_YEARS = 3.0    # need at least this much forward history to "verify"

# --------------------------------------------------------------------------
# Candidate universe.
#
# Each row: (base_symbol, company, sector, entry_date, expected_role, discovery)
#   base_symbol  : NSE base ticker; builder tries "<base>.NS" then "<base>.BO".
#   entry_date   : cohort entry (builder snaps to the nearest trading day).
#   expected_role: discovery hint ONLY (winner/control/destroyer). The final
#                  label is computed from pulled prices, not from this field.
#   discovery    : short free-source citation used to surface the candidate.
#
# Cohorts span 2010-2021 to avoid single-regime bias. Sector labels are the
# builder's coarse GICS-ish buckets; yfinance's own sector is not relied upon.
# --------------------------------------------------------------------------
CANDIDATES: list[tuple[str, str, str, str, str, str]] = [
    # ---------------- Information Technology ----------------
    ("TCS", "Tata Consultancy Services", "IT", "2010-01-01", "winner", "MotilalOswal WCS; ground_truth"),
    ("TATAELXSI", "Tata Elxsi", "IT", "2019-01-01", "winner", "stockpricearchive; ground_truth"),
    ("PERSISTENT", "Persistent Systems", "IT", "2019-01-01", "winner", "BusinessToday 2025 500-1800% list"),
    ("COFORGE", "Coforge (ex NIIT Tech)", "IT", "2016-01-01", "winner", "specialty IT re-rating"),
    ("KPITTECH", "KPIT Technologies", "IT", "2020-01-01", "winner", "auto-ER&D re-rating"),
    ("TANLA", "Tanla Platforms", "IT", "2019-01-01", "winner", "MotilalOswal WCS fastest (85% CAGR)"),
    ("MPHASIS", "Mphasis", "IT", "2016-01-01", "winner", "IT mid-cap re-rating"),
    ("WIPRO", "Wipro", "IT", "2015-01-01", "control", "large-cap IT laggard 2015-2020"),
    ("INFY", "Infosys", "IT", "2015-01-01", "control", "large-cap IT modest (FRA_V2_AUDIT spot-check)"),

    # ---------------- Pharma / Health Care ----------------
    ("AJANTPHARM", "Ajanta Pharma", "Pharma", "2012-01-01", "winner", "ACE +10399% Nov-2017; ground_truth"),
    # CAPLIPOINT yfinance history starts 2014-06; entry snapped to post-listing.
    ("CAPLIPOINT", "Caplin Point Laboratories", "Pharma", "2014-07-01", "winner", "ACE +25640% Nov-2017; ground_truth"),
    ("DIVISLAB", "Divi's Laboratories", "Pharma", "2014-01-01", "winner", "API/CDMO compounder"),
    ("LAURUSLABS", "Laurus Labs", "Pharma", "2017-01-01", "winner", "API/ARV re-rating (listed 2016)"),
    ("ABBOTINDIA", "Abbott India", "Pharma", "2014-01-01", "winner", "MNC pharma compounder"),
    ("JBCHEPHARM", "J B Chemicals & Pharma", "Pharma", "2016-01-01", "winner", "branded generics compounder"),
    ("POLYMED", "Poly Medicure", "Pharma", "2016-01-01", "winner", "medical devices compounder"),
    ("TORNTPHARM", "Torrent Pharmaceuticals", "Pharma", "2014-01-01", "winner", "branded generics"),
    ("SUNPHARMA", "Sun Pharmaceutical", "Pharma", "2015-01-01", "control", "large pharma down 2015-2020"),
    ("LUPIN", "Lupin", "Pharma", "2015-01-01", "control", "US-generics laggard 2015-2020"),
    ("DRREDDY", "Dr Reddy's Laboratories", "Pharma", "2015-01-01", "control", "flat 2015-2020"),
    ("CIPLA", "Cipla", "Pharma", "2015-01-01", "control", "flat 2015-2020"),

    # ---------------- Financials (banks / NBFC) ----------------
    ("BAJFINANCE", "Bajaj Finance", "Financials", "2012-01-01", "winner", "MotilalOswal WCS; ground_truth"),
    ("BAJFINANCE", "Bajaj Finance", "Financials", "2016-01-01", "winner", "second cohort (NBFC compounder)"),
    ("BAJAJFINSV", "Bajaj Finserv", "Financials", "2013-01-01", "winner", "financial-services holdco"),
    ("CHOLAFIN", "Cholamandalam Inv & Fin", "Financials", "2013-01-01", "winner", "FinExpress NBFC list; ground_truth"),
    ("MUTHOOTFIN", "Muthoot Finance", "Financials", "2014-01-01", "winner", "gold-loan leader; ground_truth"),
    ("AUBANK", "AU Small Finance Bank", "Financials", "2018-01-01", "winner", "SFB re-rating (listed 2017)"),
    ("HDFCBANK", "HDFC Bank", "Financials", "2010-01-01", "winner", "MotilalOswal WCS biggest creators"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Financials", "2010-01-01", "winner", "MotilalOswal WCS"),
    ("ICICIBANK", "ICICI Bank", "Financials", "2018-01-01", "winner", "asset-quality turnaround"),
    ("SBIN", "State Bank of India", "Financials", "2011-01-01", "control", "PSU bank flat 2011-2016"),
    ("PNB", "Punjab National Bank", "Financials", "2014-01-01", "destroyer", "PNB-Nirav-Modi fraud 2018"),
    ("BANKBARODA", "Bank of Baroda", "Financials", "2014-01-01", "control", "PSU bank NPA cycle"),
    ("CANBK", "Canara Bank", "Financials", "2014-01-01", "control", "PSU bank NPA cycle"),
    ("FEDERALBNK", "Federal Bank", "Financials", "2014-01-01", "control", "mid private bank modest"),

    # ---------------- FMCG / Consumer Staples ----------------
    ("AVANTIFEED", "Avanti Feeds", "FMCG", "2012-01-01", "winner", "Big Vision 83x; ground_truth"),
    ("BRITANNIA", "Britannia Industries", "FMCG", "2012-01-01", "winner", "packaged-foods compounder"),
    ("MARICO", "Marico", "FMCG", "2012-01-01", "winner", "FMCG compounder"),
    ("DABUR", "Dabur India", "FMCG", "2012-01-01", "control", "FMCG modest compounder"),
    ("VBL", "Varun Beverages", "FMCG", "2018-01-01", "winner", "ETNow 7-yr beat; stockpricearchive"),
    ("TATACONSUM", "Tata Consumer Products", "FMCG", "2018-01-01", "winner", "consumer re-rating"),
    ("NESTLEIND", "Nestle India", "FMCG", "2014-01-01", "control", "FMCG modest compounder"),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG", "2012-01-01", "control", "MotilalOswal WCS biggest (modest x)"),
    ("ITC", "ITC", "FMCG", "2015-01-01", "control", "flat 2015-2020 laggard"),
    ("COLPAL", "Colgate-Palmolive India", "FMCG", "2015-01-01", "control", "FMCG flat 2015-2020"),

    # ---------------- Auto / Auto ancillaries ----------------
    ("EICHERMOT", "Eicher Motors", "Auto", "2011-01-01", "winner", "Royal Enfield turnaround; ground_truth"),
    ("BALKRISIND", "Balkrishna Industries", "Auto", "2013-01-01", "winner", "OTR tyre exporter; ground_truth"),
    ("MOTHERSON", "Samvardhana Motherson", "Auto", "2013-01-01", "winner", "auto-ancillary global roll-up"),
    ("BOSCHLTD", "Bosch", "Auto", "2012-01-01", "control", "MNC auto modest"),
    ("MRF", "MRF", "Auto", "2012-01-01", "winner", "tyre compounder"),
    ("UNOMINDA", "Uno Minda", "Auto", "2016-01-01", "winner", "auto-ancillary compounder"),
    ("TIINDIA", "Tube Investments of India", "Auto", "2018-01-01", "winner", "Murugappa platform compounder"),
    ("BHARATFORG", "Bharat Forge", "Auto", "2014-01-01", "control", "cyclical forging"),
    ("HEROMOTOCO", "Hero MotoCorp", "Auto", "2015-01-01", "control", "2W leader flat 2015-2020"),
    ("TATAMOTORS", "Tata Motors", "Auto", "2015-01-01", "control", "BusinessInsider decade-loser list"),
    ("MARUTI", "Maruti Suzuki", "Auto", "2013-01-01", "winner", "passenger-car leader re-rating"),

    # ---------------- Chemicals / Materials ----------------
    ("DEEPAKNTR", "Deepak Nitrite", "Chemicals", "2016-01-01", "winner", "MotilalOswal WCS fastest (90% CAGR)"),
    ("SRF", "SRF", "Chemicals", "2016-01-01", "winner", "MotilalOswal WCS consistent (33% CAGR)"),
    ("NAVINFLUOR", "Navin Fluorine Intl", "Chemicals", "2017-01-01", "winner", "Ambit FY17-22 golden period"),
    ("PIDILITIND", "Pidilite Industries", "Chemicals", "2010-01-01", "winner", "Fevicol moat; ground_truth"),
    ("PIDILITIND", "Pidilite Industries", "Chemicals", "2015-01-01", "winner", "second cohort"),
    ("AARTIIND", "Aarti Industries", "Chemicals", "2016-01-01", "winner", "MotilalOswal WCS consistent (40% CAGR)"),
    ("ATUL", "Atul", "Chemicals", "2014-01-01", "winner", "BCG India-chem TSR; specialty"),
    ("VINATIORGA", "Vinati Organics", "Chemicals", "2016-01-01", "winner", "MotilalOswal WCS consistent (48% CAGR)"),
    ("BALAMINES", "Balaji Amines", "Chemicals", "2016-01-01", "winner", "Ambit amines FY17-22"),
    ("ALKYLAMINE", "Alkyl Amines Chemicals", "Chemicals", "2016-01-01", "winner", "MotilalOswal WCS consistent (79% CAGR)"),
    ("PIIND", "PI Industries", "Chemicals", "2014-01-01", "winner", "BCG agrochem TSR 55%"),
    ("FINEORG", "Fine Organic Industries", "Chemicals", "2019-01-01", "winner", "oleochemicals (listed 2018)"),
    ("TATACHEM", "Tata Chemicals", "Chemicals", "2014-01-01", "control", "commodity soda-ash cyclical"),
    ("ASIANPAINT", "Asian Paints", "Materials", "2010-01-01", "winner", "distribution moat; ground_truth"),
    ("BERGEPAINT", "Berger Paints India", "Materials", "2012-01-01", "winner", "#2 paints; ground_truth"),
    ("SHREECEM", "Shree Cement", "Materials", "2012-01-01", "winner", "low-cost cement compounder"),
    ("ULTRACEMCO", "UltraTech Cement", "Materials", "2015-01-01", "control", "cement leader modest 2015-2020"),
    ("GRASIM", "Grasim Industries", "Materials", "2015-01-01", "control", "diversified holdco modest"),

    # ---------------- Capital Goods / Defense / Building materials ----------------
    ("ASTRAL", "Astral", "CapitalGoods", "2015-01-01", "winner", "MotilalOswal WCS consistent (45% CAGR)"),
    ("APLAPOLLO", "APL Apollo Tubes", "CapitalGoods", "2016-01-01", "winner", "MotilalOswal WCS fastest (60% CAGR)"),
    ("HAVELLS", "Havells India", "CapitalGoods", "2012-01-01", "winner", "electricals brand; ground_truth"),
    ("KAJARIACER", "Kajaria Ceramics", "CapitalGoods", "2012-01-01", "winner", "tile leader; ground_truth"),
    ("DIXON", "Dixon Technologies", "CapitalGoods", "2019-01-01", "winner", "EMS/PLI; ground_truth"),
    # POLYCAB IPO Apr-2019; entry snapped to post-listing.
    ("POLYCAB", "Polycab India", "CapitalGoods", "2019-05-01", "winner", "Lakshmishree 5y +982% (listed 2019)"),
    ("SIEMENS", "Siemens", "CapitalGoods", "2016-01-01", "winner", "Lakshmishree 5y +500%"),
    ("ABB", "ABB India", "CapitalGoods", "2016-01-01", "winner", "Lakshmishree 5y +435%"),
    ("BEL", "Bharat Electronics", "Defense", "2016-01-01", "winner", "Lakshmishree 5y +720%; defense"),
    ("HAL", "Hindustan Aeronautics", "Defense", "2020-01-01", "winner", "Lakshmishree 5y +1409% (listed 2018)"),
    ("BDL", "Bharat Dynamics", "Defense", "2019-01-01", "winner", "defense missiles (listed 2018)"),
    ("MAZDOCK", "Mazagon Dock Shipbuilders", "Defense", "2021-01-01", "winner", "defense shipbuilder (listed 2020)"),
    ("KEI", "KEI Industries", "CapitalGoods", "2016-01-01", "winner", "wires & cables compounder"),
    ("SUPREMEIND", "Supreme Industries", "CapitalGoods", "2012-01-01", "winner", "plastics compounder"),
    ("CUMMINSIND", "Cummins India", "CapitalGoods", "2014-01-01", "control", "capital-goods modest"),
    ("THERMAX", "Thermax", "CapitalGoods", "2016-01-01", "control", "capital-goods cyclical"),
    ("LT", "Larsen & Toubro", "CapitalGoods", "2010-01-01", "control", "infra bellwether modest"),
    ("BHEL", "Bharat Heavy Electricals", "CapitalGoods", "2010-01-01", "destroyer", "Rediff/PetroBazaar -90% m-cap"),

    # ---------------- Metals / Mining (mostly cyclical controls) ----------------
    ("JSWSTEEL", "JSW Steel", "Metals", "2016-01-01", "winner", "steel up-cycle 2016-2021"),
    ("HINDALCO", "Hindalco Industries", "Metals", "2010-01-01", "control", "aluminium cyclical"),
    ("TATASTEEL", "Tata Steel", "Metals", "2010-01-01", "control", "steel cyclical flat decade"),
    ("COALINDIA", "Coal India", "Metals", "2011-01-01", "destroyer", "below 2010 IPO price; BusinessInsider"),
    ("NMDC", "NMDC", "Metals", "2011-01-01", "destroyer", "PetroBazaar -78% decade"),
    ("SAIL", "Steel Authority of India", "Metals", "2011-01-01", "destroyer", "PetroBazaar -87% decade"),
    ("VEDL", "Vedanta", "Metals", "2010-01-01", "control", "diversified metals cyclical"),
    ("JINDALSTEL", "Jindal Steel & Power", "Metals", "2010-01-01", "control", "steel/power leveraged cyclical"),

    # ---------------- Energy / Utilities / Infra (controls + a couple winners) ----------------
    ("ONGC", "Oil & Natural Gas Corp", "Energy", "2010-01-01", "destroyer", "PetroBazaar -53% decade"),
    ("GAIL", "GAIL India", "Energy", "2011-01-01", "control", "PetroBazaar -20% decade"),
    ("IOC", "Indian Oil Corp", "Energy", "2011-01-01", "control", "PSU refiner modest"),
    ("NTPC", "NTPC", "Utilities", "2011-01-01", "control", "PetroBazaar -47% decade (pre-2021)"),
    ("POWERGRID", "Power Grid Corp", "Utilities", "2011-01-01", "control", "regulated utility modest"),
    ("TATAPOWER", "Tata Power", "Utilities", "2011-01-01", "control", "BusinessInsider decade flat (pre-2021)"),
    ("ADANIENT", "Adani Enterprises", "Infra", "2016-01-01", "winner", "MotilalOswal WCS most-consistent (86% CAGR)"),
    ("ADANIPORTS", "Adani Ports & SEZ", "Infra", "2016-01-01", "winner", "ports platform re-rating"),

    # ---------------- Consumer Discretionary / Retail ----------------
    ("TITAN", "Titan Company", "Consumer", "2010-01-01", "winner", "brand/pricing power; ground_truth"),
    ("TITAN", "Titan Company", "Consumer", "2016-01-01", "winner", "second cohort"),
    ("PAGEIND", "Page Industries", "Consumer", "2010-01-01", "winner", "Jockey licensee; ground_truth"),
    # SYMPHONY yfinance history starts 2011-06; entry snapped to post-listing.
    ("SYMPHONY", "Symphony", "Consumer", "2011-07-01", "winner", "asset-light air coolers; ground_truth"),
    ("JUBLFOOD", "Jubilant FoodWorks", "Consumer", "2014-01-01", "winner", "Domino's India QSR compounder"),
    ("RELAXO", "Relaxo Footwears", "Consumer", "2012-01-01", "winner", "value footwear; ground_truth"),
    ("TRENT", "Trent", "Consumer", "2016-01-01", "winner", "ETNow 7-yr beat; Zudio (BusinessToday +1050%)"),
    ("TRENT", "Trent", "Consumer", "2019-01-01", "winner", "second cohort (Zudio scale-up)"),
    ("VOLTAS", "Voltas", "Consumer", "2014-01-01", "winner", "cooling products re-rating"),
    ("VGUARD", "V-Guard Industries", "Consumer", "2014-01-01", "winner", "electricals compounder"),
    ("WHIRLPOOL", "Whirlpool of India", "Consumer", "2015-01-01", "control", "appliances flat post-2018"),
    ("BATAINDIA", "Bata India", "Consumer", "2015-01-01", "control", "footwear modest"),

    # ---------------- Industrials (logistics / bearings) ----------------
    ("CONCOR", "Container Corp of India", "Industrials", "2011-01-01", "control", "PSU logistics modest decade"),
    ("SKFINDIA", "SKF India", "Industrials", "2014-01-01", "winner", "bearings industrial compounder"),
    ("TIMKEN", "Timken India", "Industrials", "2016-01-01", "winner", "bearings industrial compounder"),

    # ---------------- Value destroyers (extreme controls; many may be delisted) ----------------
    ("YESBANK", "Yes Bank", "Financials", "2018-01-01", "destroyer", "governance/AT1 write-off; destroyers.csv"),
    ("SUZLON", "Suzlon Energy", "CapitalGoods", "2010-01-01", "destroyer", "debt/cash-burn; destroyers.csv"),
    ("RPOWER", "Reliance Power", "Utilities", "2010-01-01", "destroyer", "ADA governance; destroyers.csv"),
    ("RELINFRA", "Reliance Infrastructure", "Utilities", "2010-01-01", "destroyer", "ADA leverage; destroyers.csv"),
    ("IDEA", "Vodafone Idea", "Telecom", "2017-01-01", "destroyer", "AGR/price-war; destroyers.csv"),
    ("IBULHSGFIN", "Indiabulls Housing Finance", "Financials", "2018-01-01", "destroyer", "NBFC ALM stress; destroyers.csv"),
    ("DISHTV", "Dish TV India", "Telecom", "2017-01-01", "destroyer", "obsolescence/pledge; destroyers.csv"),
    ("HATHWAY", "Hathway Cable & Datacom", "Telecom", "2017-01-01", "destroyer", "cable obsolescence; destroyers.csv"),
    ("VAKRANGEE", "Vakrangee", "IT", "2018-01-01", "destroyer", "auditor red flag; destroyers.csv"),
    ("RCOM", "Reliance Communications", "Telecom", "2010-01-01", "destroyer", "insolvency 2019; destroyers.csv"),
    ("JETAIRWAYS", "Jet Airways", "Industrials", "2018-01-01", "destroyer", "grounded 2019; destroyers.csv"),
    ("GITANJALI", "Gitanjali Gems", "Consumer", "2012-01-01", "destroyer", "PNB fraud/liquidation; destroyers.csv"),
    ("KFA", "Kingfisher Airlines", "Industrials", "2010-01-01", "destroyer", "delisted 2015; destroyers.csv"),
    ("DHFL", "Dewan Housing Finance", "Financials", "2018-01-01", "destroyer", "fraud/delisted; destroyers.csv"),
    ("MANPASAND", "Manpasand Beverages", "FMCG", "2018-01-01", "destroyer", "auditor exit/delisted; destroyers.csv"),
    ("RELCAPITAL", "Reliance Capital", "Financials", "2010-01-01", "destroyer", "CIRP/auditor resign; destroyers.csv"),

    # ======================================================================
    # V2 Phase-5 additions: de-survivorship + PIT-determinacy expansion.
    #
    # Rationale (docs/FRA_V2_BACKTEST_RESULTS.md Phase 5): determinacy is bounded
    # by screener's free depth (~FY2015), so PIT-determinate names concentrate in
    # the 2016-2021 cohorts. These additions therefore (a) lengthen the
    # determinate 2017-2021 slice with more sector/cohort diversity, and (b)
    # deliberately add DELISTED / FAILED value-destroyers (debt collapses, frauds,
    # PSU-bank NPA cycles, IL&FS/NBFC-crisis casualties) wherever ANY free price
    # history survives - putting losers back into the test to fight survivorship
    # bias. Multiples remain computed from actually-pulled prices; names with no
    # free history / <3y forward data are DROPPED by the builder (that absence is
    # itself survivorship evidence, reported in the drop list).
    #
    # NOTE: capital-market-infra / AMC / broker names are bucketed "CapitalMarkets"
    # (not "Financials") so the screen treats them as non-financials (ROCE gate),
    # which is correct - they are asset-light fee businesses, not lending books.
    # ----------------------------------------------------------------------
    # ---- Winners (deep-screener 2017-2021 cohorts, sector-diverse) ----
    ("DMART", "Avenue Supermarts", "Consumer", "2018-01-01", "winner", "value retail compounder (listed 2017)"),
    ("CDSL", "Central Depository Services", "CapitalMarkets", "2019-01-01", "winner", "depository monopoly (listed 2017)"),
    ("IEX", "Indian Energy Exchange", "CapitalMarkets", "2019-01-01", "winner", "power-exchange monopoly (listed 2017)"),
    ("HDFCAMC", "HDFC Asset Management", "CapitalMarkets", "2019-01-01", "winner", "AMC franchise (listed 2018)"),
    ("CAMS", "Computer Age Management Services", "CapitalMarkets", "2021-01-01", "winner", "MF RTA duopoly (listed 2020)"),
    ("ANGELONE", "Angel One", "CapitalMarkets", "2021-06-01", "winner", "discount broker scale-up (listed 2020)"),
    ("AFFLE", "Affle India", "IT", "2020-01-01", "winner", "adtech compounder (listed 2019)"),
    ("ROUTE", "Route Mobile", "IT", "2021-01-01", "winner", "CPaaS (listed 2020)"),
    ("HAPPSTMNDS", "Happiest Minds Technologies", "IT", "2021-01-01", "winner", "digital IT (listed 2020)"),
    ("INTELLECT", "Intellect Design Arena", "IT", "2018-01-01", "winner", "fintech product re-rating"),
    ("MASTEK", "Mastek", "IT", "2018-01-01", "winner", "mid-cap IT re-rating"),
    ("SAREGAMA", "Saregama India", "Consumer", "2020-01-01", "winner", "music-IP monetisation"),
    ("RADICO", "Radico Khaitan", "Consumer", "2017-01-01", "winner", "premium spirits re-rating"),
    ("CROMPTON", "Crompton Greaves Consumer", "Consumer", "2017-01-01", "winner", "consumer electricals (listed 2016)"),
    ("KPRMILL", "K.P.R. Mill", "Consumer", "2017-01-01", "winner", "integrated textiles compounder"),
    ("RATNAMANI", "Ratnamani Metals & Tubes", "CapitalGoods", "2017-01-01", "winner", "SS pipes niche leader"),
    ("GARFIBRES", "Garware Technical Fibres", "CapitalGoods", "2017-01-01", "winner", "technical textiles"),
    ("SUMICHEM", "Sumitomo Chemical India", "Chemicals", "2018-01-01", "winner", "agrochem (listed 2018)"),
    ("GLAND", "Gland Pharma", "Pharma", "2021-06-01", "winner", "injectables CDMO (listed 2020)"),
    ("LALPATHLAB", "Dr Lal PathLabs", "Pharma", "2017-01-01", "winner", "diagnostics chain (listed 2015)"),
    ("APLLTD", "Alembic Pharmaceuticals", "Pharma", "2017-01-01", "winner", "branded/generic pharma"),
    ("SOLARINDS", "Solar Industries India", "Chemicals", "2017-01-01", "winner", "explosives/defense compounder"),
    ("CENTURYPLY", "Century Plyboards", "CapitalGoods", "2016-01-01", "winner", "plywood/laminates brand"),
    ("CERA", "Cera Sanitaryware", "CapitalGoods", "2015-01-01", "winner", "sanitaryware brand"),

    # ---- Controls / value-destroyers (2016-2019; de-survivorship focus) ----
    ("GMRINFRA", "GMR Infrastructure", "Infra", "2016-01-01", "control", "airport/infra leveraged holdco"),
    ("JPASSOCIAT", "Jaiprakash Associates", "Infra", "2016-01-01", "destroyer", "debt collapse / insolvency"),
    ("JISLJALEQS", "Jain Irrigation Systems", "Industrials", "2016-01-01", "destroyer", "working-capital/debt collapse"),
    ("SINTEX", "Sintex Industries", "Industrials", "2016-01-01", "destroyer", "debt collapse / insolvency"),
    ("PCJEWELLER", "PC Jeweller", "Consumer", "2017-01-01", "destroyer", "governance/receivables collapse"),
    ("MCLEODRUSS", "McLeod Russel India", "FMCG", "2017-01-01", "destroyer", "tea debt/ICD diversion collapse"),
    ("GVKPIL", "GVK Power & Infrastructure", "Infra", "2016-01-01", "destroyer", "infra debt collapse"),
    ("HCC", "Hindustan Construction", "Infra", "2016-01-01", "control", "leveraged EPC, chronic underperformer"),
    ("SADBHAV", "Sadbhav Engineering", "Infra", "2017-01-01", "destroyer", "road-EPC debt/BOT collapse"),
    ("COFFEEDAY", "Coffee Day Enterprises", "Consumer", "2019-01-01", "destroyer", "promoter debt/diversion collapse"),
    ("CGPOWER", "CG Power & Industrial", "CapitalGoods", "2017-01-01", "control", "accounting fraud 2019 (pre-turnaround)"),
    ("PNBHOUSING", "PNB Housing Finance", "Financials", "2018-01-01", "control", "NBFC-crisis ALM stress (listed 2016)"),
    ("UJJIVAN", "Ujjivan Financial Services", "Financials", "2017-01-01", "control", "SFB holdco, MFI stress"),
    ("BANKINDIA", "Bank of India", "Financials", "2016-01-01", "control", "PSU bank NPA cycle"),
    ("UNIONBANK", "Union Bank of India", "Financials", "2016-01-01", "control", "PSU bank NPA cycle"),
    ("IDBI", "IDBI Bank", "Financials", "2016-01-01", "destroyer", "PSU bank near-collapse / PCA"),
    ("EDELWEISS", "Edelweiss Financial Services", "Financials", "2018-01-01", "control", "diversified NBFC stress"),
    ("RNAVAL", "Reliance Naval & Engineering", "CapitalGoods", "2017-01-01", "destroyer", "ADA shipyard insolvency (may be delisted)"),
    ("SREINFRA", "SREI Infrastructure Finance", "Financials", "2017-01-01", "destroyer", "NBFC insolvency (may be delisted)"),
]


# --------------------------------------------------------------------------
# yfinance access with a small on-disk cache (idempotent re-runs).
# --------------------------------------------------------------------------
def _load_cache(yahoo_symbol: str):
    path = os.path.join(_CACHE, f"{yahoo_symbol}.csv")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.reader(fh):
            if len(r) < 2:
                continue
            try:
                d = datetime.strptime(r[0], "%Y-%m-%d").date()
                c = float(r[1])
            except (ValueError, TypeError):
                continue
            if c > 0:
                rows.append((d, c))
    return rows or None


def _save_cache(yahoo_symbol: str, rows: list[tuple[date, float]]) -> None:
    os.makedirs(_CACHE, exist_ok=True)
    path = os.path.join(_CACHE, f"{yahoo_symbol}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for d, c in rows:
            w.writerow([d.isoformat(), f"{c:.6f}"])


def _pull_yf(yahoo_symbol: str):
    """Return list[(date, adj_close)] ascending, or None on failure."""
    import yfinance as yf

    try:
        df = yf.Ticker(yahoo_symbol).history(period="max", auto_adjust=True)
    except Exception:
        return None
    if df is None or df.empty or "Close" not in df.columns:
        return None
    rows: list[tuple[date, float]] = []
    for ts, row in df.iterrows():
        try:
            c = float(row["Close"])
        except (TypeError, ValueError, KeyError):
            continue
        if c and c > 0:
            rows.append((ts.date(), c))
    return rows or None


def get_history(base_symbol: str, refresh: bool):
    """Resolve base -> (.NS, .BO), return (yahoo_symbol, rows) or (None, None)."""
    for suffix in (".NS", ".BO"):
        ysym = base_symbol + suffix
        rows = None if refresh else _load_cache(ysym)
        if rows is None:
            rows = _pull_yf(ysym)
            if rows:
                _save_cache(ysym, rows)
        if rows and len(rows) >= 60:
            return ysym, rows
    return None, None


# --------------------------------------------------------------------------
# Price lookups / multiple computation.
# --------------------------------------------------------------------------
def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def price_asof(rows: list[tuple[date, float]], target: date, tol_days: int = DATE_TOL_DAYS):
    """Nearest trading-day close to `target` within +/- tol_days. (date, close) or None."""
    best = None
    best_gap = None
    for d, c in rows:
        gap = abs((d - target).days)
        if gap <= tol_days and (best_gap is None or gap < best_gap):
            best_gap = gap
            best = (d, c)
    return best


def peak_in_window(rows, start: date, end: date):
    """(peak_date, peak_close) with max close in [start, end], or None."""
    best = None
    for d, c in rows:
        if start <= d <= end:
            if best is None or c > best[1]:
                best = (d, c)
    return best


def label_from_multiples(peak_mult, mult_5y, full_5y: bool) -> tuple[str, str]:
    """Return (label, basis).

    Winner labels are PEAK-based (a name that reached >=3x/5x at any point in the
    window WAS a multibagger you could have realized). The control/intermediate
    cut is REALIZED-5y-based so a transient pop that later collapsed is correctly
    treated as a non_multibagger control rather than "intermediate".
    """
    if peak_mult is None:
        return "unlabeled_partial", "no entry/peak price"
    if peak_mult >= STRONG_X:
        return "multibagger_strong", "peak reached >=5x within window"
    if peak_mult >= MULTI_X:
        return "multibagger", "peak reached >=3x within window"
    # Never a 3-bagger at peak -> need the full 5y to judge control vs intermediate.
    if not full_5y:
        return "unlabeled_partial", "window <5y and peak never reached 3x"
    # Prefer realized 5y multiple; fall back to peak if 5y price unavailable.
    ref = mult_5y if mult_5y is not None else peak_mult
    if ref < CONTROL_X:
        basis = "full 5y, realized 5y <1.5x" if mult_5y is not None else "full 5y, peak <1.5x"
        return "non_multibagger", basis
    return "intermediate", "full 5y, peak <3x and realized 5y in [1.5x,3x)"


def build_row(cand, refresh: bool):
    base, company, sector, entry_s, role, discovery = cand
    entry = _parse(entry_s)
    ysym, rows = get_history(base, refresh)
    if not rows:
        return None, f"DROP {base} ({entry_s}): no price history (likely delisted)"

    first_date = rows[0][0]
    last_date = rows[-1][0]

    entry_hit = price_asof(rows, entry)
    if entry_hit is None:
        return None, (
            f"DROP {base} ({entry_s}): history starts {first_date}, "
            f"entry not priceable within {DATE_TOL_DAYS}d"
        )
    entry_price_date, entry_price = entry_hit

    fwd_years = (last_date - entry_price_date).days / 365.25
    if fwd_years < MIN_FWD_YEARS:
        return None, (
            f"DROP {base} ({entry_s}): only {fwd_years:.1f}y forward data "
            f"(need >= {MIN_FWD_YEARS}y)"
        )

    # 3y / 5y realized multiples.
    d3 = price_asof(rows, entry + timedelta(days=int(365.25 * 3)))
    d5 = price_asof(rows, entry + timedelta(days=int(365.25 * 5)))
    price_3y = d3[1] if d3 else None
    price_5y = d5[1] if d5 else None
    mult_3y = round(price_3y / entry_price, 3) if price_3y else None
    mult_5y = round(price_5y / entry_price, 3) if price_5y else None

    # Peak inside the 5y window (bounded by available data).
    window_end = entry + timedelta(days=int(365.25 * 5))
    obs_end = min(window_end, last_date)
    full_5y = last_date >= window_end
    pk = peak_in_window(rows, entry_price_date, obs_end)
    peak_price_5y = pk[1] if pk else None
    peak_mult_5y = round(peak_price_5y / entry_price, 3) if peak_price_5y else None

    label, basis = label_from_multiples(peak_mult_5y, mult_5y, full_5y)

    holding_years = round(min(fwd_years, 5.0), 2)

    notes = (
        f"role={role}; discovery={discovery}; entry~{entry_price_date.isoformat()}; "
        f"hist {first_date.isoformat()}..{last_date.isoformat()}; "
        f"5y_window_complete={full_5y}; label_basis={basis}"
    )

    row = {
        "ticker": base,
        "yahoo_symbol": ysym,
        "company": company,
        "sector": sector,
        "entry_date": entry_s,
        "entry_price": round(entry_price, 4),
        "price_3y": round(price_3y, 4) if price_3y else "",
        "mult_3y": mult_3y if mult_3y is not None else "",
        "price_5y": round(price_5y, 4) if price_5y else "",
        "mult_5y": mult_5y if mult_5y is not None else "",
        "peak_price_5y": round(peak_price_5y, 4) if peak_price_5y else "",
        "peak_mult_5y": peak_mult_5y if peak_mult_5y is not None else "",
        "holding_years_available": holding_years,
        "label": label,
        "data_source": "yfinance (auto_adjust=splits+dividends)",
        "verified": True,
        "notes": notes,
    }
    return row, None


FIELDS = [
    "ticker", "yahoo_symbol", "company", "sector", "entry_date", "entry_price",
    "price_3y", "mult_3y", "price_5y", "mult_5y", "peak_price_5y", "peak_mult_5y",
    "holding_years_available", "label", "data_source", "verified", "notes",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="force re-pull from yfinance")
    args = ap.parse_args()

    os.makedirs(_DATA, exist_ok=True)

    rows: list[dict] = []
    drops: list[str] = []
    for cand in CANDIDATES:
        try:
            row, drop = build_row(cand, args.refresh)
        except Exception as e:  # never let one ticker kill the run
            drop = f"ERROR {cand[0]} ({cand[3]}): {e}"
            row = None
        if row:
            rows.append(row)
            print(
                f"  OK  {row['yahoo_symbol']:<16} {row['entry_date']}  "
                f"peak={row['peak_mult_5y']}x  5y={row['mult_5y']}x  -> {row['label']}"
            )
        else:
            drops.append(drop)
            print(f"  --  {drop}")

    # Deterministic ordering: sector, then entry_date, then ticker.
    rows.sort(key=lambda r: (r["sector"], r["entry_date"], r["ticker"]))

    with open(_OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    # ---- Summary to stdout ----
    from collections import Counter

    by_label = Counter(r["label"] for r in rows)
    by_sector = Counter(r["sector"] for r in rows)
    by_cohort = Counter(r["entry_date"][:4] for r in rows)

    print("\n" + "=" * 60)
    print(f"WROTE {_OUT_CSV}")
    print(f"labeled rows : {len(rows)}    dropped: {len(drops)}")
    print("\nby label:")
    for k, v in sorted(by_label.items(), key=lambda x: -x[1]):
        print(f"  {k:<20} {v}")
    print("\nby sector:")
    for k, v in sorted(by_sector.items()):
        print(f"  {k:<16} {v}")
    print("\nby cohort (entry year):")
    for k, v in sorted(by_cohort.items()):
        print(f"  {k}  {v}")
    print("\ndropped candidates:")
    for d in drops:
        print(f"  {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
