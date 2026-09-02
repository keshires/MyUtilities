import asyncio
import datetime
import os
from pathlib import Path
from xml.sax.saxutils import escape

import aiohttp
import nest_asyncio
from dotenv import load_dotenv

nest_asyncio.apply()
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def _req(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        raise SystemExit(
            f"Missing required environment variable: {name}. See .env.example."
        )
    return val


URL = os.getenv(
    "RISKCALC_SECURITY_SOAP_URL",
    "https://api-security.riskcalc.moodysanalytics.com/services/security/internal/Security.svc",
).strip()


def _soap_body() -> str:
    wsse_u = escape(_req("RISKCALC_WSSE_USERNAME"))
    wsse_p = escape(_req("RISKCALC_WSSE_PASSWORD"))
    nonce = escape(_req("RISKCALC_SOAP_NONCE"))
    created = escape(_req("RISKCALC_SOAP_CREATED"))
    auth_u = escape(_req("RISKCALC_AUTH_BODY_USERNAME"))
    auth_p = escape(_req("RISKCALC_AUTH_BODY_PASSWORD"))
    return f"""<soapenv:Envelope xmlns:arr="http://schemas.microsoft.com/2003/10/Serialization/Arrays" xmlns:ns="http://services.moodyskmv.com/security/2009/03/" xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
   <soapenv:Header><wsse:Security soapenv:mustUnderstand="1" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><wsse:UsernameToken wsu:Id="UsernameToken-7375EFCF4E0FD4783A17527905647345"><wsse:Username>{wsse_u}</wsse:Username><wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText">{wsse_p}</wsse:Password><wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce}</wsse:Nonce><wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security></soapenv:Header>
    <soapenv:Body>
        <ns:AuthenticateAndGetUserInfo>
            <ns:userName>{auth_u}</ns:userName>
            <ns:password>{auth_p}</ns:password>
        </ns:AuthenticateAndGetUserInfo>
    </soapenv:Body>
</soapenv:Envelope>
"""


DATA = _soap_body()

HEADERS = {
    "Content-Type": "text/xml; charset=utf-8",
    "SOAPAction": "AuthenticateAndGetUserInfo",
}


async def make_request(
    session: aiohttp.ClientSession, i: int, print_response: bool = False
) -> None:
    try:
        async with session.post(URL, headers=HEADERS, data=DATA) as response:
            print(f"Request {i}: Status {response.status}")
            if print_response:
                response_text = await response.text()
                print(f"Request {i}: Response {response_text}")
    except Exception as e:
        print(f"Request {i}: Failed with error {e}")


async def main(print_response: bool = False) -> None:
    start_date = datetime.datetime.today()
    print(f"Request Process started @ {start_date}")

    async with aiohttp.ClientSession() as session:
        tasks = [make_request(session, i, print_response) for i in range(1, 1000)]
        await asyncio.gather(*tasks)

    print(
        f"Request Process started @ {start_date} and Completed @ {datetime.datetime.today()}"
    )


if __name__ == "__main__":
    asyncio.run(main(print_response=False))
