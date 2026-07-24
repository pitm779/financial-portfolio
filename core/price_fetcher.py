import yfinance as yf
import pandas as pd
from datetime import date


def get_current_price(ticker: str) -> float:
    ticker_data = yf.Ticker(ticker)

    return ticker_data.fast_info["lastPrice"]

def get_history_price(tickers: list[str], start_date: date, end_date: date) -> pd.DataFrame:
    df = yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date,
        interval="1d"
    )

    return df["Close"]


if __name__ == "__main__":
    current_price = get_current_price("XTB.WA")
    close_prices = get_history_price(["XTB.WA", "PZU.WA", "PKN.WA"], "2026-07-01", "2026-07-05")

    print(current_price)
    print(close_prices)