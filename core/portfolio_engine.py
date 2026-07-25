from dataclasses import dataclass, field
from sqlmodel import Session, select
import database.tables as tables
from core.price_fetcher import get_current_price
import pandas as pd

@dataclass
class PositionSummary:
    ticker: str
    asset_type: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float = field(init=False)
    unrealized_profit: float = field(init=False)

    def __post_init__(self):
        self.market_value = self.quantity * self.current_price
        self.unrealized_profit = (self.current_price - self.avg_cost) * self.quantity

def calculate_assets(session: Session):
    assets = session.exec(select(tables.Asset)).all()
    portfolio = []

    for asset in assets:
        asset_transactions = sorted(asset.transactions, key=lambda tx: tx.timestamp)

        total_qty = 0
        total_cost = 0

        for i in asset_transactions:
            if i.transaction_type == tables.TransactionType.BUY:
                total_qty += i.quantity
                total_cost += (i.price_per_unit * i.quantity) + i.fee
            elif i.transaction_type == tables.TransactionType.SELL:
                if total_qty > 0:
                    avg_cost = total_cost / total_qty
                    total_qty -= i.quantity
                    total_cost -= (avg_cost * i.quantity)

        if total_qty > 0:
            avg_cost = total_cost / total_qty
            current_price = get_current_price(asset.ticker) or 0

            summary = PositionSummary(
                ticker = asset.ticker,
                asset_type = asset.asset_type.value,
                quantity = total_qty,
                avg_cost = avg_cost,
                current_price = current_price
            )
            portfolio.append(summary)
    return portfolio

def calculate_portfolio_history(all_transactions, start_date, end_date, prices_df: pd.DataFrame):
    if not all_transactions or prices_df.empty:
        return pd.Series(dtype=float)

    tx_records = []
    for tx in all_transactions:
        if not tx.asset:
            continue
        tx_type_str = tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)
        tx_records.append({
            "ticker": tx.asset.ticker,
            "type": tx_type_str.upper(),
            "quantity": float(tx.quantity),
            "date": pd.to_datetime(tx.timestamp).tz_localize(None)
        })

    if not tx_records:
        return pd.Series(dtype=float)

    df_tx = pd.DataFrame(tx_records)

    start_ts = pd.to_datetime(start_date).tz_localize(None)
    end_ts = pd.to_datetime(end_date).tz_localize(None)

    earliest_date = min(df_tx['date'].min(), start_ts)
    full_date_range = pd.date_range(start=earliest_date, end=end_ts)

    all_tickers = df_tx['ticker'].unique().tolist()
    changes_df = pd.DataFrame(0.0, index=full_date_range, columns=all_tickers)

    for _, tx in df_tx.iterrows():
        tx_date = tx['date'].normalize()
        t = tx['ticker']
        qty = tx['quantity'] if tx['type'] == "BUY" else -tx['quantity']
        if tx_date in changes_df.index:
            changes_df.loc[tx_date, t] += qty

    holdings_df = changes_df.cumsum()

    if isinstance(prices_df, pd.Series):
        prices_df = prices_df.to_frame(name=all_tickers[0])

    if isinstance(prices_df.columns, pd.MultiIndex):
        prices_df.columns = prices_df.columns.get_level_values(-1)

    prices_df.index = pd.to_datetime(prices_df.index).tz_localize(None)

    holdings_trading_days = holdings_df.reindex(prices_df.index, method="ffill").fillna(0.0)

    common_cols = [c for c in prices_df.columns if c in holdings_trading_days.columns]
    daily_values = prices_df[common_cols] * holdings_trading_days[common_cols]
    daily_values = daily_values.ffill().bfill()

    daily_values_window = daily_values.loc[start_ts:end_ts]
    return daily_values_window.sum(axis=1)