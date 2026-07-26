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

    trade_types = ["Stock purchase", "Stock sale", "DIVIDENT", "Withholding Tax", "deposit"]
    trades_df = df[df["Type"].isin(trade_types)].copy()
    
    parsed_transactions = []
    trade_pattern = r"(?:OPEN|CLOSE)\s+(?:BUY|SELL)?\s*(?P<qty>\d+(?:\.\d+)?)(?:\s*/\s*[\d.]+)?\s*@\s*(?P<price>\d+(?:\.\d+)?)"
    
    for _, row in trades_df.iterrows():
        raw_symbol = str(row.get("Symbol", "")).strip()
        row_type = str(row.get("Type", "")).strip()
        comment = str(row.get("Comment", "")).strip()
        amount = abs(float(row.get("Amount", 0.0)))
        
        if row_type in ["Stock purchase", "Stock sale"]:
            ticker = fix_xtb_ticker(raw_symbol)
            tx_type = TransactionType.BUY if row_type == "Stock purchase" else TransactionType.SELL
            
            match = re.search(trade_pattern, comment, re.IGNORECASE)
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
                    price_per_unit = amount

            parsed_transactions.append({
                "ticker": ticker,
                "transaction_type": tx_type,
                "quantity": quantity,
                "price_per_unit": price_per_unit,
                "fee": 0.0,
                "currency": "PLN",
                "timestamp": pd.to_datetime(row["Time"]).date()
            })

        elif row_type in ["DIVIDENT"]:
            ticker = fix_xtb_ticker(raw_symbol)
            
            dps_match = re.search(r"(?:PLN|USD|EUR)?\s*(?P<dps>\d+(?:\.\d+)?)\s*/\s*SHR", comment, re.IGNORECASE)
            
            if dps_match:
                price_per_unit = float(dps_match.group("dps"))
                quantity = round(amount / price_per_unit, 4) if price_per_unit > 0 else 1.0
            else:
                price_per_unit = amount
                quantity = 1.0

            parsed_transactions.append({
                "ticker": ticker,
                "transaction_type": TransactionType.DIVIDEND,
                "quantity": quantity,
                "price_per_unit": price_per_unit,
                "fee": 0.0,
                "currency": "PLN",
                "timestamp": pd.to_datetime(row["Time"]).date()
            })

        elif row_type in ["Withholding Tax"]:
            ticker = fix_xtb_ticker(raw_symbol)

            parsed_transactions.append({
                "ticker": ticker,
                "transaction_type": TransactionType.TAX,
                "quantity": 1.0,
                "price_per_unit": amount,
                "fee": 0.0,
                "currency": "PLN",
                "timestamp": pd.to_datetime(row["Time"]).date()
            })

        elif row_type in ["deposit"]:
            parsed_transactions.append({
                "ticker": "PLN",
                "transaction_type": TransactionType.DEPOSIT,
                "quantity": amount,
                "price_per_unit": 1.0,
                "fee": 0.0,
                "currency": "PLN",
                "timestamp": pd.to_datetime(row["Time"]).date()
            })

        elif row_type in ["withdrawal"]:
            parsed_transactions.append({
            "ticker": "PLN",
            "transaction_type": TransactionType.WITHDRAWAL,
            "quantity": amount,
            "price_per_unit": 1.0,
            "fee": 0.0,
            "currency": "PLN",
            "timestamp": pd.to_datetime(row["Time"]).date()
        })
        
    return pd.DataFrame(parsed_transactions)