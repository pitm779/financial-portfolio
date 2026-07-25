import streamlit as st
from database.connection import init_db, engine
from sqlmodel import Session, select
from core.portfolio_engine import calculate_assets, calculate_portfolio_history
import database.tables as tables
from datetime import date, timedelta
from core.price_fetcher import get_history_price
import pandas as pd
from core.borker_parser import parse_xtb_excel

init_db()

tab1, tab2, tab3, tab4 = st.tabs(["📈 Portfolio", "Add Asset", "Transaction", "Import Statement"])

with tab1:
    if st.button("Refresh"):
        st.rerun()
    with Session(engine) as session:
        portfolio = calculate_assets(session)
        all_transactions = session.exec(select(tables.Transactions)).all()
        if portfolio:
            total_val = sum(pos.market_value for pos in portfolio)
            total_pnl = sum(pos.unrealized_profit for pos in portfolio)
            
            col1, col2 = st.columns(2)
            col1.metric("Total Market Value", f"{total_val:,.2f} PLN")
            col2.metric("Unrealized Profit", f"{total_pnl:,.2f} PLN")
            
            st.dataframe(portfolio, use_container_width=True)
            
            st.markdown("---")
            st.subheader("📈 Historical Performance")
            
            timeframe = st.selectbox(
                "Select Timeframe", 
                ["1 Month", "3 Months", "6 Months", "1 Year", "5 Year", "YTD"], 
                index=1
            )
            
            end_date = date.today()
            if timeframe == "1 Month":
                start_date = end_date - timedelta(days=30)
            elif timeframe == "3 Months":
                start_date = end_date - timedelta(days=90)
            elif timeframe == "6 Months":
                start_date = end_date - timedelta(days=180)
            elif timeframe == "1 Year":
                start_date = end_date - timedelta(days=365)
            elif timeframe == "5 Year":
                            start_date = end_date - timedelta(days=365*5)
            elif timeframe == "YTD":
                start_date = date(end_date.year, 1, 1)

            tickers = list(set([tx.asset.ticker for tx in all_transactions if tx.asset]))
            
            with st.spinner("Fetching historical market data..."):
                prices_df = get_history_price(tickers, start_date, end_date)

            if not prices_df.empty:
                total_series = calculate_portfolio_history(all_transactions, start_date, end_date, prices_df)
                st.line_chart(total_series)
            else:
                st.warning("Could not fetch historical price data for the selected timeframe.")                
        else:
            st.info("No active positions found. Add an asset and a transaction to get started!")
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
with tab4:
    st.subheader("📤 Import Broker Statement")
    
    broker = st.selectbox("Select Broker", ["XTB"])
    uploaded_file = st.file_uploader("Upload XTB Excel File (.xlsx)", type=["xlsx"])
    
    if uploaded_file is not None:
        #try:
            if broker == "XTB":
                parsed_df = parse_xtb_excel(uploaded_file)
            
            if not parsed_df.empty:
                st.markdown("### Preview Parsed Transactions")
                st.dataframe(parsed_df, use_container_width=True)
                
                if st.button("Confirm & Save to Portfolio"):
                    with Session(engine) as session:
                        count = 0
                        for _, row in parsed_df.iterrows():
                            asset_stmt = select(tables.Asset).where(tables.Asset.ticker == row["ticker"])
                            asset = session.exec(asset_stmt).first()
                            
                            if not asset:
                                asset = tables.Asset(
                                    ticker=row["ticker"],
                                    name=row["ticker"],
                                    asset_type=tables.AssetType.STOCK,
                                    currency=row["currency"]
                                )
                                session.add(asset)
                                session.commit()
                                session.refresh(asset)
                            
                            tx = tables.Transactions(
                                asset_id=asset.id,
                                transaction_type=row["transaction_type"],
                                quantity=row["quantity"],
                                price_per_unit=row["price_per_unit"],
                                fee=row["fee"],
                                currency=row["currency"],
                                timestamp=row["timestamp"]
                            )
                            session.add(tx)
                            count += 1
                            
                        session.commit()
                        st.success(f"Successfully imported {count} transactions!")
                        st.rerun()
            else:
                st.warning("No stock purchase or sale transactions found in the file.")
                
        #except Exception as e:
        #    st.error(f"Failed to parse file: {e}")