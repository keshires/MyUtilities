import httpx
import requests


def call_resolve():
    # literal path -> linkable
    return requests.post("/entity/v1/resolve", json={})


def call_var(url):
    # bare variable target -> not linkable (partial)
    return requests.get(url)


async def call_session(session, base):
    return await session.get(base + "/financials/client/v1/ratios")


def not_http(d):
    # client hint absent -> ignored
    return d.get("key")
