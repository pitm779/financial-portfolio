from dataclasses import dataclass
from sqlmodel import Session, select
import database.tables as tables
from core.price_fetcher import get_current_price

@dataclass
class PositionSummary:
    ticker: str
    asset_type: str
    quantity: float
    avg_cost: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_profit(self) -> float:
        return (self.current_price - self.avg_cost) * self.quantity


def calculate_assets(session: Session):
    assets = session.exec(select(tables.Asset)).all()
    portfolio = []

    for asset in assets:
        asset_transactions = asset.transactions

        total_qty = 0
        total_cost = 0

        for i in asset_transactions:
            if i.transaction_type == tables.TransactionType.BUY:
                total_qty += i.quantity
                total_cost += (i.price_per_unit * i.quantity) + i.fee
            elif i.transaction_type == tables.TransactionType.SELL:
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