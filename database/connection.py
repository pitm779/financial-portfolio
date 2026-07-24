from sqlmodel import create_engine, SQLModel, Session
import database.tables

sqlite_url = "sqlite:///portfolio.db"

engine = create_engine(sqlite_url, echo = False)

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

if __name__ == "__main__":
    init_db()
    print("DB and tables created")