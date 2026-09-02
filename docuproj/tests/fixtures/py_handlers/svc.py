import requests
from fastapi import APIRouter

r = APIRouter(prefix="/p")


class Thing:
    pass


def _fetch():
    return requests.get("http://svc/data")  # outbound, in a helper


def _read(session):
    return session.query(Thing).all()  # db, in a helper


@r.get("/list")
def list_things(session):
    _fetch()  # handler -> helper (outbound)
    return _read(session)  # handler -> helper (db)