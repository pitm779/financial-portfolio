import streamlit as st
from database.connection import init_db, engine
from sqlmodel import Session, select
from core.portfolio_engine import calculate_assets
import database.tables as tables

init_db()

tab1, tab2, tab3 = st.tabs(["Portfolio", "Add Asset", "Transaction"])

with tab1:
    if st.button("Refresh"):
        st.rerun()
    with Session(engine) as session:
        portfolio = calculate_assets(session)
        st.dataframe(portfolio)
with tab2:
    with st.form("add_asset_form"):
        ticker = st.text_input("Ticker Symbol").upper()
        asset_type = st.selectbox("Asset Type", [i.value for i in tables.AssetType])
        currency = st.selectbox("Currency", ["PLN"])

        submitted = st.form_submit_button("Save Asset")
        if submitted:
            with Session(engine) as session:
                new_asset = tables.Asset(
                    ticker=ticker, 
                    name="name", 
                    asset_type=tables.AssetType(asset_type), 
                    currency=currency
                )
                session.add(new_asset)
                session.commit()
                st.success(f"Added {ticker}")
with tab3:
    with Session(engine) as session:
        assets = session.exec(select(tables.Asset)).all()
        asset_map = {a.ticker: a.id for a in assets}

    with st.form("add_transaction_form"):
            asset_id = st.selectbox("Asset Ticker", list(asset_map.keys()))
            transaction_type = st.selectbox("Transaction Type", [i.value for i in tables.TransactionType])
            quantity = st.number_input("Quantity")
            price_per_unit = st.number_input("Price Per Unit")
            fee = st.number_input("Fee")
            currency = st.selectbox("Currency", ["PLN"])
            timestamp = st.datetime_input("Date")
    
            submitted = st.form_submit_button("Save Transaction")
            if submitted:
                with Session(engine) as session:
                    new_transaction = tables.Transactions(
                        asset_id=asset_map[asset_id], 
                        transaction_type=tables.TransactionType(transaction_type),
                        quantity=quantity,
                        price_per_unit=price_per_unit,
                        fee=fee,
                        currency=currency,
                        timestamp=timestamp
                    )
                    session.add(new_transaction)
                    session.commit()
                    st.success(f"Added transaction on {ticker}")
