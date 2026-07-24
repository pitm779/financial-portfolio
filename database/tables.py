from enum import Enum
from datetime import datetime, date
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class AssetType(str, Enum):
    STOCK = "Stock"
    BOND = "Bond"
    GOV_BOND = "Gov Bond"
    CASH = "Cash"
    CRYPTO = "Crypto"
    BANK_DEPOSIT = "Bank Deposit"
    ETF = "ETF"

class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    INTEREST = "Interest"
    DEPOSIT = "Deposit"
    WITHDRAWAL = "Withdrawal"
    FEE = "Fee"
    TAX = "Tax"
    SPLIT = "Split"

class Asset(SQLModel, table = True):
    id: Optional[int] = Field(default = None, primary_key = True)
    ticker: str = Field(index = True)
    name: str
    asset_type: AssetType
    currency: str

    transactions: List["Transactions"] = Relationship(back_populates = "asset")

class Transactions(SQLModel, table = True):
    id: Optional[int] = Field(default = None, primary_key = True)
    asset_id: int = Field(foreign_key = "asset.id")
    transaction_type: TransactionType = Field(index = True)
    quantity: float
    price_per_unit: float
    fee: float = Field(default = 0.0)
    tax: float = Field(default = 0.0)
    currency: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None

    asset: Optional[Asset] = Relationship(back_populates = "transactions")

class PriceHistory(SQLModel, table = True):
    id: Optional[int] = Field(default = None, primary_key = True)
    ticker: str = Field(index = True)
    price_date: date = Field(index = True)
    close_price: float