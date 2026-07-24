import pandas as pd
import re
from database.tables import TransactionType

def fix_xtb_ticker(symbol: str) -> str:
    if symbol.endswith(".PL"):
        return symbol.replace(".PL", ".WA")
    elif symbol.endswith(".US"):
        return symbol.replace(".US", "")
    return symbol

def parse_xtb_excel(file):
    df = pd.read_excel(file, sheet_name="CASH OPERATION HISTORY", skiprows=10)

    trade_types = ["Stock purchase", "Stock sale"]
    trades_df = df[df["Type"].isin(trade_types)].copy()
    
    parsed_transactions = []
    pattern = r"(?:OPEN|CLOSE)\s+(?:BUY|SELL)?\s*(?P<qty>\d+(?:\.\d+)?)(?:\s*/\s*[\d.]+)?\s*@\s*(?P<price>\d+(?:\.\d+)?)"
    
    for _, row in trades_df.iterrows():
        raw_symbol = str(row.get("Symbol", "")).strip()
        ticker = fix_xtb_ticker(raw_symbol)
        
        tx_type = TransactionType.BUY if row["Type"] == "Stock purchase" else TransactionType.SELL
        comment = str(row.get("Comment", ""))
        
        match = re.search(pattern, comment, re.IGNORECASE)
        
        if match:
            quantity = float(match.group("qty"))
            price_per_unit = float(match.group("price"))
        else:
            fallback_match = re.search(r"(?P<qty>\d+(?:\.\d+)?)\s*@\s*(?P<price>\d+(?:\.\d+)?)", comment)
            if fallback_match:
                quantity = float(fallback_match.group("qty"))
                price_per_unit = float(fallback_match.group("price"))
            else:
                quantity = 1.0
                price_per_unit = abs(float(row.get("Amount", 0.0)))
            
        parsed_transactions.append({
            "ticker": ticker,
            "transaction_type": tx_type,
            "quantity": quantity,
            "price_per_unit": price_per_unit,
            "fee": 0.0,
            "currency": "PLN",
            "timestamp": pd.to_datetime(row["Time"]).date()
        })
        
    return pd.DataFrame(parsed_transactions)