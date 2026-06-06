"""
universes.py — ticker lists for supported index universes.
SP500 / NDX100 lists are representative samples; swap in a full
list or fetch dynamically via FMP /api/v3/sp500_constituent.
"""
from typing import Dict, List

SP500: List[str] = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","BRK-B","JPM",
    "LLY","V","UNH","XOM","MA","JNJ","PG","HD","AVGO","MRK","ABBV","CVX",
    "KO","PEP","ADBE","CRM","TMO","ACN","MCD","CSCO","BAC","WMT","DIS",
    "NFLX","INTC","AMD","QCOM","TXN","GS","MS","HON","RTX","CAT","IBM",
    "GE","BA","MMM","AMGN","BMY","GILD","SCHW","BLK","AXP","SPGI","CB",
    "C","WFC","USB","PNC","TFC","AIG","MET","PRU","AFL","ALL","CI","HUM",
    "MDT","ABT","SYK","BSX","ELV","DHR","ISRG","ZTS","REGN","VRTX","BIIB",
    "ILMN","IQV","A","DXCM","IDXX","BAX","BDX","COO","CAH","MCK","ABC",
    "ANTM","UHS","HCA","THC","CNC","MOH","WBA","CVS","RAD","ESRX",
    "NEE","DUK","SO","D","AEP","EXC","SRE","XEL","ES","FE","ETR","PPL",
    "NI","CNP","OKE","WEC","CMS","ATO","LNT","NWE","EVRG","POR",
    "AMT","PLD","CCI","EQIX","PSA","SPG","O","VICI","WELL","DLR","EQR",
    "AVB","MAA","UDR","CPT","ESS","AIV","NNN","STAG","IIPR","COLD",
    "LIN","APD","ECL","SHW","PPG","EMN","CE","LYB","DOW","DD","FMC",
    "NUE","STLD","RS","CMC","ATI","X","CLF","AA","HCC","ARCH",
]

NDX100: List[str] = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","COST","ADBE",
    "CSCO","NFLX","AMD","QCOM","TXN","INTC","AMGN","INTU","AMAT","MU",
    "LRCX","KLAC","MRVL","PANW","SNPS","CDNS","REGN","MDLZ","GILD","PYPL",
    "ADI","FTNT","MELI","ABNB","IDXX","DXCM","AEP","XEL","FANG","CSGP",
    "WDAY","TEAM","ZS","CRWD","OKTA","MNST","KDP","PCAR","DLTR","FAST",
    "ROST","PAYX","ADP","VRSK","ANSS","CPRT","ODFL","SIRI","WBA","FISV",
    "VRSN","MTCH","NXPI","SWKS","MCHP","KEYS","ZBRA","TTWO","EA","ATVI",
    "LULU","ORLY","BKNG","CHTR","CMCSA","TMUS","T","VZ","SBUX","HON",
]

DOW30: List[str] = [
    "AAPL","MSFT","UNH","GS","HD","MCD","AMGN","CAT","BA","HON",
    "IBM","JPM","JNJ","V","PG","CVX","MRK","MMM","WMT","DIS",
    "TRV","NKE","AXP","DOW","CSCO","CRM","INTC","KO","VZ","WBA",
]

UNIVERSES: Dict[str, List[str]] = {
    "sp500":     SP500,
    "nasdaq100": NDX100,
    "dowjones":  DOW30,
}


def get_tickers(universe: str, max_tickers: int = 0) -> List[str]:
    """Return ticker list for a named universe, optionally capped."""
    tickers = UNIVERSES.get(universe.lower(), [])
    if max_tickers and max_tickers < len(tickers):
        tickers = tickers[:max_tickers]
    return tickers
