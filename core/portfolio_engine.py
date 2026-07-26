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
        tx_type_str = tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)
        if tx_type_str in ["BUY", "SELL"]:
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
        qty = tx["quantity"] if tx["type"] == "BUY" else -tx["quantity"]
        if tx_date in changes_df.index:
            changes_df.loc[tx_date, t] += qty

    holdings_df = changes_df.cumsum()

    if isinstance(prices_df, pd.Series):
        prices_df = prices_df.to_frame(name=all_tickers[0])
    if isinstance(prices_df.columns, pd.MultiIndex):
        prices_df.columns = prices_df.columns.get_level_values(-1)

    prices_df.index = pd.to_datetime(prices_df.index).tz_localize(None)
    holdings_trading_days = holdings_df.reindex(
        prices_df.index, method="ffill"
    ).fillna(0.0)

    common_cols = [
        c for c in prices_df.columns if c in holdings_trading_days.columns
    ]
    daily_values = prices_df[common_cols] * holdings_trading_days[common_cols]
    daily_values = daily_values.ffill().bfill()
    portfolio_series = daily_values.sum(axis=1)

    cash_changes = pd.Series(0.0, index=full_date_range)

    for tx in all_transactions:
        tx_type_str = (
            tx.transaction_type.value
            if hasattr(tx.transaction_type, "value")
            else str(tx.transaction_type)
        ).lower()
        if tx_type_str in ["deposit", "withdrawal"]:
            tx_date = pd.to_datetime(tx.timestamp).tz_localize(None).normalize()
            if tx_date in cash_changes.index:
                amount = float(tx.price_per_unit * tx.quantity)
                if tx_type_str == "deposit":
                    cash_changes.loc[tx_date] += abs(amount)
                elif tx_type_str == "withdrawal":
                    cash_changes.loc[tx_date] -= abs(amount)

    prices_df.index = pd.to_datetime(prices_df.index).tz_localize(None)
    cumulative_cash = (
        cash_changes.cumsum().reindex(prices_df.index, method="ffill").fillna(0.0)
    )

    history_df = pd.DataFrame({
        "Portfolio Value": portfolio_series,
        "Net Cash Flow": cumulative_cash,
    })

    return history_df.loc[start_ts:end_ts]

def get_asset_type_summary(portfolio: list):
    unique_types = [item.value for item in tables.AssetType]
    asset_data = []
    if portfolio:
        for pos in portfolio:
            raw_type = getattr(
                pos,
                "asset_type",
                getattr(getattr(pos, "asset", None), "asset_type", "Other"),
            )
            asset_type_str = (
                raw_type.value if hasattr(raw_type, "value") else str(raw_type)
            )

            asset_data.append({
                "Type": asset_type_str,
                "Market Value": float(pos.market_value or 0.0),
                "Unrealised Profit": float(pos.unrealized_profit or 0.0),
            })

    if asset_data:
        df_active = (
            pd.DataFrame(asset_data).groupby("Type", as_index=False).sum()
        )
    else:
        df_active = pd.DataFrame(
            columns=["Type", "Market Value", "Unrealised Profit"]
        )

    df_master = pd.DataFrame({"Type": unique_types})
    df_merged = pd.merge(df_master, df_active, on="Type", how="left").fillna(0.0)
    total_val = df_merged["Market Value"].sum()
    df_merged["% of Wallet"] = (
        (df_merged["Market Value"] / total_val * 100) if total_val > 0 else 0.0
    )

    # Sort descending by Market Value
    df_merged = df_merged.sort_values(
        by="Market Value", ascending=False
    ).reset_index(drop=True)

    return df_merged[
        ["Type", "Market Value", "% of Wallet", "Unrealised Profit"]
    ]