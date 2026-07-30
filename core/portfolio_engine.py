from dataclasses import dataclass, field
from sqlmodel import Session, select
import database.tables as tables
from core.price_fetcher import get_current_price, get_history_price
import pandas as pd
from datetime import date, timedelta
from scipy.optimize import newton, brentq
import numpy as np

@dataclass
class PositionSummary:
    ticker: str
    asset_type: str
    quantity: float
    avg_cost: float
    current_price: float
    prev_close_price: float = 0.0
    
    market_value: float = field(init=False)
    unrealized_profit: float = field(init=False)
    unrealized_profit_pct: float = field(init=False)
    daily_change: float = field(init=False)
    daily_change_pct: float = field(init=False)

    def __post_init__(self):
        self.market_value = self.quantity * self.current_price
        self.unrealized_profit = (self.current_price - self.avg_cost) * self.quantity
        
        # Calculate overall percentage gain
        total_cost = self.avg_cost * self.quantity
        self.unrealized_profit_pct = (self.unrealized_profit / total_cost * 100) if total_cost > 0 else 0.0

        # Calculate 1-Day Delta
        if self.prev_close_price > 0:
            self.daily_change = (self.current_price - self.prev_close_price) * self.quantity
            self.daily_change_pct = ((self.current_price - self.prev_close_price) / self.prev_close_price) * 100
        else:
            self.daily_change = 0.0
            self.daily_change_pct = 0.0

def calculate_assets(session: Session):
    assets = session.exec(select(tables.Asset)).all()
    portfolio = []
    holdings = {}
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
            holdings[asset.ticker] = {
                "asset_type": asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type),
                "quantity": total_qty,
                "avg_cost": avg_cost,
            }

    if not holdings:
        return []

    end_date = date.today()
    start_date = end_date - timedelta(days=5)
    tickers = list(holdings.keys())
    
    prices_df = get_history_price(tickers, start_date, end_date)

    portfolio = []
    for ticker, data in holdings.items():
        current_price = get_current_price(ticker) or 0.0
        prev_close_price = 0.0

        if not prices_df.empty:
            if isinstance(prices_df, pd.Series):
                df_ticker = prices_df
            elif ticker in prices_df.columns:
                df_ticker = prices_df[ticker]
            else:
                df_ticker = pd.Series(dtype=float)

            if not df_ticker.empty:
                prev_prices = df_ticker[df_ticker.index.date < end_date].dropna()
                if not prev_prices.empty:
                    prev_close_price = float(prev_prices.iloc[-1])

        if prev_close_price == 0.0:
            prev_close_price = current_price

        summary = PositionSummary(
            ticker=ticker,
            asset_type=data["asset_type"],
            quantity=data["quantity"],
            avg_cost=data["avg_cost"],
            current_price=current_price,
            prev_close_price=prev_close_price
        )
        portfolio.append(summary)

    return portfolio

def calculate_portfolio_history(all_transactions: list, start_date, end_date, prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates daily portfolio history including both stock value and uninvested cash balance.
    """
    if not all_transactions or prices_df.empty:
        return pd.DataFrame()

    # 1. Create a continuous daily date range
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    
    # 2. Sort transactions chronologically
    sorted_txs = sorted(all_transactions, key=lambda x: pd.to_datetime(x.timestamp))

    records = []
    running_cash = 0.0
    net_injected_cash = 0.0
    running_holdings = {}  # ticker -> quantity
    
    tx_idx = 0
    n_txs = len(sorted_txs)

    # Convert prices_df index to date objects for fast matching
    prices_df_clean = prices_df.copy()
    prices_df_clean.index = pd.to_datetime(prices_df_clean.index).date

    for current_dt in date_range:
        cur_date = current_dt.date()

        # Process all transactions that occurred on or before cur_date
        while tx_idx < n_txs and pd.to_datetime(sorted_txs[tx_idx].timestamp).date() <= cur_date:
            tx = sorted_txs[tx_idx]
            tx_type = (tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)).lower()
            
            ticker = tx.asset.ticker if hasattr(tx, 'asset') and tx.asset else str(getattr(tx, 'ticker', ''))
            quantity = float(tx.quantity)
            price = float(tx.price_per_unit)
            amount = quantity * price
            fee = float(getattr(tx, 'fee', 0.0) or 0.0)

            if tx_type == "deposit":
                running_cash += (amount - fee)
                net_injected_cash += amount
            elif tx_type == "withdrawal":
                running_cash -= (amount + fee)
                net_injected_cash -= amount
            elif tx_type == "buy":
                running_cash -= (amount + fee)
                running_holdings[ticker] = running_holdings.get(ticker, 0.0) + quantity
            elif tx_type == "sell":
                running_cash += (amount - fee)
                running_holdings[ticker] = running_holdings.get(ticker, 0.0) - quantity
            elif tx_type == "dividend":
                running_cash += (amount - fee)
            elif tx_type == "tax":
                running_cash -= amount

            tx_idx += 1

        # 3. Calculate total stock market value for cur_date
        stock_value = 0.0
        for ticker, qty in running_holdings.items():
            if qty > 0.0001 and ticker in prices_df_clean.columns:
                # Find most recent available market price
                valid_prices = prices_df_clean[ticker].loc[prices_df_clean.index <= cur_date].dropna()
                if not valid_prices.empty:
                    stock_value += qty * float(valid_prices.iloc[-1])

        # 4. Total Portfolio Value = Stocks + Uninvested Cash
        total_portfolio_value = stock_value + running_cash

        records.append({
            "Date": cur_date,
            "Portfolio Value": total_portfolio_value,
            "Net Cash Flow": net_injected_cash,
            "Stock Value": stock_value,
            "Cash Balance": running_cash
        })
    history_df = pd.DataFrame(records)
    if not history_df.empty:
        history_df.set_index("Date", inplace=True)
    return history_df

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


    if not (has_pos and has_neg):
        return np.nan

    d0 = dates[0]
    day_diffs = [(d - d0).days / 365.0 for d in dates]

    def npv(r):
        if r <= -0.999:
            return 1e12
        return sum(cf / ((1.0 + r) ** t) for cf, t in zip(cash_flows, day_diffs))

    try:
        r_min, r_max = -0.999, 10.0
        f_min, f_max = npv(r_min), npv(r_max)

        if f_min * f_max < 0:
            rate = brentq(npv, r_min, r_max, maxiter=100)
        else:
            rate = newton(npv, 0.10, maxiter=50)

        rate_pct = float(rate * 100)

        if rate_pct > 500.0 or rate_pct < -100.0:
            return np.nan

        return rate_pct

    except Exception:
        return np.nan

def calculate_xirr(dates: list, cash_flows: list) -> float:
    """
    Calculates XIRR safely with bounded root finding and day-span sanity checks.
    """
    if len(cash_flows) < 2 or len(dates) < 2:
        return np.nan

    days_span = (dates[-1] - dates[0]).days
    if days_span < 30:
        return np.nan

    has_pos = any(c > 0 for c in cash_flows)
    has_neg = any(c < 0 for c in cash_flows)
    if not (has_pos and has_neg):
        return np.nan

    d0 = dates[0]
    day_diffs = [(d - d0).days / 365.0 for d in dates]

    def npv(r):
        if r <= -0.999:
            return 1e12
        return sum(cf / ((1.0 + r) ** t) for cf, t in zip(cash_flows, day_diffs))

    try:
        r_min, r_max = -0.999, 10.0
        f_min, f_max = npv(r_min), npv(r_max)

        if f_min * f_max < 0:
            rate = brentq(npv, r_min, r_max, maxiter=100)
        else:
            rate = newton(npv, 0.10, maxiter=50)

        rate_pct = float(rate * 100)

        if rate_pct > 500.0 or rate_pct < -100.0:
            return np.nan

        return rate_pct

    except Exception:
        return np.nan

def calculate_xirr_history(all_transactions: list, total_series) -> pd.Series:
    """
    Computes historical rolling XIRR for each date in total_series.
    Strictly prioritizes DEPOSIT/WITHDRAWAL cash flows to avoid double-counting.
    """
    if total_series is None or len(total_series) == 0 or not all_transactions:
        return pd.Series(dtype=float)

    if isinstance(total_series, pd.DataFrame):
        if "Portfolio Value" in total_series.columns:
            total_series = total_series["Portfolio Value"]
        else:
            total_series = total_series.iloc[:, 0]

    # 1. Check if user has explicit deposit/withdrawal records
    has_explicit_deposits = any(
        (tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)).lower() in ["deposit", "withdrawal"]
        for tx in all_transactions
    )

    # 2. Parse cash flows without double counting
    cfs_list = []
    for tx in all_transactions:
        tx_type = (tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)).lower()
        tx_date = pd.to_datetime(tx.timestamp).date()
        amount = float(tx.price_per_unit * tx.quantity)

        if has_explicit_deposits:
            # ONLY count external transfers into/out of the brokerage account
            if tx_type == "deposit":
                cfs_list.append((tx_date, -abs(amount)))
            elif tx_type == "withdrawal":
                cfs_list.append((tx_date, abs(amount)))
        else:
            # Fallback if user only records buys/sells
            if tx_type == "buy":
                cfs_list.append((tx_date, -abs(amount)))
            elif tx_type == "sell":
                cfs_list.append((tx_date, abs(amount)))

    if not cfs_list:
        return pd.Series(np.nan, index=total_series.index)

    cfs_list.sort(key=lambda x: x[0])
    portfolio_start_date = cfs_list[0][0]

    xirr_results = {}
    for eval_date, current_val in total_series.items():
        try:
            eval_dt = pd.to_datetime(eval_date).date()
        except Exception:
            continue

        # 90-day warm-up window from first deposit date
        days_since_start = (eval_dt - portfolio_start_date).days
        if days_since_start < 90:
            xirr_results[eval_date] = np.nan
            continue

        historical_cfs = [(d, cf) for d, cf in cfs_list if d <= eval_dt]

        if not historical_cfs or current_val <= 0 or pd.isna(current_val):
            xirr_results[eval_date] = np.nan
            continue

        # Virtual liquidation cash flow on evaluation date (+)
        dates = [d for d, _ in historical_cfs] + [eval_dt]
        cfs = [cf for _, cf in historical_cfs] + [float(current_val)]

        xirr_val = calculate_xirr(dates, cfs)
        xirr_results[eval_date] = xirr_val

    xirr_series = pd.Series(xirr_results)
    xirr_series.name = "XIRR (%)"
    return xirr_series