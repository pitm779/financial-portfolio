import streamlit as st
import pandas as pd
from sqlmodel import Session, select
from datetime import date, timedelta
import plotly.express as px

from database.connection import init_db, engine
import database.tables as tables
from core.portfolio_engine import calculate_assets, get_asset_type_summary, calculate_portfolio_history
from core.price_fetcher import get_history_price
from core.borker_parser import parse_xtb_excel

init_db()
st.set_page_config(page_title="Financial Portfolio", layout="wide")

st.markdown(
    """
    <style>
    /* Adjust tab label text size */
    div[data-testid="stTab"] div[data-testid="stMarkdownContainer"] p {
        font-size: 22px !important;  /* Change to your preferred font size */
        font-weight: 600 !important; /* Optional: Make it bold for extra emphasis */
    }

    [data-testid="stMainBlockContainer"] {
        padding-top: 2rem !important;    /* Góra: zmniejszona z 2rem do 1rem */
        padding-bottom: 2rem !important; /* Dół */
        padding-left: 2rem !important;   /* Lewo */
        padding-right: 2rem !important;  /* Prawo */
        height: 100% !important;
    }
    /* Target ONLY the DataFrame within the transactions container */
    .st-key-transactions_table_wrapper [data-testid="stDataFrame"] {
        height: 75vh !important;
    }

    .st-key-transactions_table_wrapper [data-testid="stDataFrame"] > div {
        height: 100% !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4 = st.tabs(["📈 Portfolio", "Assets", "Transactions", "Import Statement"])

@st.dialog("Add New Asset")
def add_asset_dialog():
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
                    st.rerun()

@st.dialog("Add New Transaction")
def add_transaction_dialog():
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
                            st.success(f"Added transaction")
                            st.rerun()
    
with st.sidebar:
    with Session(engine) as session:
        st.subheader("Portfolio Summary")
    
    with Session(engine) as session:
        portfolio = calculate_assets(session)
        all_transactions = session.exec(select(tables.Transactions)).all()
        
        total_val = sum(pos.market_value for pos in portfolio) if portfolio else 0.0
        total_pnl = sum(pos.unrealized_profit for pos in portfolio) if portfolio else 0.0
        
        cash_val = 0.0
        dividends = 0.0
        for tx in all_transactions:
            if tx.transaction_type == tables.TransactionType.DIVIDEND:
                dividends += (tx.quantity * tx.price_per_unit) - tx.tax
                cash_val += (tx.quantity * tx.price_per_unit) - tx.tax
            elif tx.transaction_type == tables.TransactionType.DEPOSIT:
                cash_val += (tx.quantity * tx.price_per_unit)
            elif tx.transaction_type == tables.TransactionType.WITHDRAWAL:
                cash_val -= (tx.quantity * tx.price_per_unit)
            elif tx.transaction_type == tables.TransactionType.BUY:
                cash_val -= (tx.quantity * tx.price_per_unit) - tx.tax
            elif tx.transaction_type == tables.TransactionType.SELL:
                cash_val += (tx.quantity * tx.price_per_unit) - tx.tax

        summary_items = [
            {"Metric": "Account Value", "Value": f"{total_val:,.2f} PLN"},
            {"Metric": "Open Positions", "Value": f"{total_val:,.2f} PLN"},
            {"Metric": "Cash", "Value": f"{cash_val:,.2f} PLN"},
            {"Metric": "Unrealized Profit", "Value": f"{total_pnl:,.2f} PLN"},
            {"Metric": "Dividends Received", "Value": f"{dividends:,.2f} PLN"},
        ]
        
        df_summary = pd.DataFrame(summary_items)
        st.table(df_summary)

        st.markdown("---")
        st.caption("Currencies in Portfolio")
        st.table(pd.DataFrame([
            {"Currency": "PLN", "Value": f"{total_val:,.2f} PLN"}
        ]))

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

            col1, col2 = st.columns(2)
            df_grouped = get_asset_type_summary(portfolio)

            df_display = df_grouped.copy()
            df_display["Market Value"] = df_display["Market Value"].apply(lambda x: f"{x:,.2f} PLN")
            df_display["% of Wallet"] = df_display["% of Wallet"].apply(lambda x: f"{x:.2f}%")
            df_display["Unrealised Profit"] = df_display["Unrealised Profit"].apply(lambda x: f"{x:,.2f} PLN")

            st.subheader("Asset Breakdown")
            with col1:
                st.table(df_display)
            with col2:
                df_chart = df_grouped[df_grouped["Market Value"] > 0]
                fig = px.pie(
                    df_chart,
                    names="Type",
                    values="Market Value",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                
                fig.update_traces(textinfo="percent+label", hovertemplate="%{label}: %{value:,.2f} PLN (%{percent})")
                fig.update_layout(
                    showlegend=False,
                    margin=dict(t=20, b=20, l=10, r=10),
                    height=320
                )
                
                st.plotly_chart(fig, use_container_width=True)
            
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

            tickers = list(
                set([
                    tx.asset.ticker
                    for tx in all_transactions
                    if tx.asset
                    and tx.transaction_type
                    in [tables.TransactionType.BUY, tables.TransactionType.SELL]
                ])
            )
            
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
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.subheader("Assets")
    with col_btn:
        if st.button("Add Asset", type="primary", width="stretch"):
            add_asset_dialog()

    with Session(engine) as session:
            portfolio = calculate_assets(session)
            if portfolio:
                total_val = sum(pos.market_value for pos in portfolio)
                total_pnl = sum(pos.unrealized_profit for pos in portfolio)
                
                col1, col2 = st.columns(2)
                col1.metric("Total Market Value", f"{total_val:,.2f} PLN")
                col2.metric("Unrealized Profit", f"{total_pnl:,.2f} PLN")
                
                st.dataframe(portfolio, width="stretch")
    
with tab3:   
    with Session(engine) as session:
        assets = session.exec(select(tables.Asset)).all()
        asset_map = {a.ticker: a.id for a in assets}

    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.subheader("Transactions")
    with col_btn:
        if st.button("Add Transaction", type="primary", width="stretch"):
            add_transaction_dialog()

    with st.container(key="transactions_table_wrapper"):
        with Session(engine) as session:
            tx_stmt = select(tables.Transactions, tables.Asset).join(tables.Asset).order_by(tables.Transactions.timestamp.desc())
            results = session.exec(tx_stmt).all()

            if results:
                formatted_transactions = []
                for tx, asset in results:
                    tx_type = tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)
                    total_value = (tx.quantity * tx.price_per_unit) + tx.fee

                    formatted_transactions.append({
                        "ID": tx.id,
                        "Date": tx.timestamp.strftime("%Y-%m-%d") if hasattr(tx.timestamp, 'strftime') else str(tx.timestamp)[:10],
                        "Ticker": asset.ticker,
                        "Type": tx_type,
                        "Quantity": round(tx.quantity, 6),
                        "Price / Unit": f"{tx.price_per_unit:,.2f} {tx.currency}",
                        "Fee": f"{tx.fee:,.2f} {tx.currency}",
                        "Total Value": f"{total_value:,.2f} {tx.currency}",
                        "Notes": tx.notes or ""
                    })

                tx_df = pd.DataFrame(formatted_transactions)
                
                st.dataframe(tx_df, width="stretch", hide_index=True)
            else:
                st.info("No transactions found. Click 'Add Transaction' or import a broker statement to get started!")

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
                st.dataframe(parsed_df, width="stretch")
                
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