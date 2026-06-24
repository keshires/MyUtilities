from sqlalchemy.orm import Session


class Portfolio:
    pass


def list_portfolios(session: Session):
    # SQLAlchemy ORM query
    return session.query(Portfolio).all()


def raw_lookup(conn):
    # raw SQL string
    return conn.execute("SELECT id, name FROM portfolios WHERE tenant = :t")


def not_db(d):
    # no persistence here
    return d.get("key")