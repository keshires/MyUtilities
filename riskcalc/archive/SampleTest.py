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


URL = _req("RISKCALC_REST_URL")


def _headers() -> dict[str, str]:
    cookie = _req("RISKCALC_REST_SESSION_COOKIE")
    return {
        "Content-Type": "application/xml",
        "Cookie": cookie,
    }


def _data_xml(user_id: str) -> str:
    password = escape(_req("RISKCALC_REST_PASSWORD"))
    return f"""<RISKCALC>
    <AUTHENTICATION>
        <USERID>{escape(user_id)}</USERID>
        <PASSWORD>{password}</PASSWORD>
    </AUTHENTICATION>
    <OPERATION-LIST>
        <OPERATION FUNCTION="EDFCLC" MODEL="PRV" SUBMODEL="USA40EDF" CURRENCY="USD">
            <ARGUMENT-LIST>
                <ARGUMENT TYPE="CashAndMarketableSecurities">1</ARGUMENT>
                <ARGUMENT TYPE="Inventories">1</ARGUMENT>
                <ARGUMENT TYPE="PrevInventories">1</ARGUMENT>
                <ARGUMENT TYPE="AccountsReceivable">1</ARGUMENT>
                <ARGUMENT TYPE="PrevAccountsReceivable">1</ARGUMENT>
                <ARGUMENT TYPE="TotalAssets">1</ARGUMENT>
                <ARGUMENT TYPE="PrevTotalAssets">1</ARGUMENT>
                <ARGUMENT TYPE="AccountsPayable">1</ARGUMENT>
                <ARGUMENT TYPE="PrevAccountsPayable">1</ARGUMENT>
                <ARGUMENT TYPE="CurrentLiabilities">1</ARGUMENT>
                <ARGUMENT TYPE="TotalLongTermDebt">1</ARGUMENT>
                <ARGUMENT TYPE="TotalLiabilities">1</ARGUMENT>
                <ARGUMENT TYPE="RetainedEarnings">1</ARGUMENT>
                <ARGUMENT TYPE="NetSales">1</ARGUMENT>
                <ARGUMENT TYPE="PrevNetSales">1</ARGUMENT>
                <ARGUMENT TYPE="AmortizationAndDepreciation">1</ARGUMENT>
                <ARGUMENT TYPE="OperatingProfit">1</ARGUMENT>
                <ARGUMENT TYPE="InterestExpense">1</ARGUMENT>
                <ARGUMENT TYPE="NetIncome">1</ARGUMENT>
                <ARGUMENT TYPE="PrevNetIncome">1</ARGUMENT>
                <ARGUMENT TYPE="UserDefinedTimePeriod">1</ARGUMENT>
                <ARGUMENT TYPE="Verbose">8</ARGUMENT>
                <ARGUMENT TYPE="FirmID">123</ARGUMENT>
                <ARGUMENT TYPE="FirmName">123</ARGUMENT>
                <ARGUMENT TYPE="FinancialStmntOnly">false</ARGUMENT>
                <ARGUMENT TYPE="CurrentDay">19</ARGUMENT>
                <ARGUMENT TYPE="CurrentMonth">3</ARGUMENT>
                <ARGUMENT TYPE="CurrentYear">2020</ARGUMENT>
                <ARGUMENT TYPE="StatementDay">19</ARGUMENT>
                <ARGUMENT TYPE="StatementMonth">3</ARGUMENT>
                <ARGUMENT TYPE="StatementYear">2020</ARGUMENT>
                <ARGUMENT TYPE="IndustryDefinition">UNASSIGNED</ARGUMENT>
                <ARGUMENT TYPE="IndustryClassification">SECTOR</ARGUMENT>
                <ARGUMENT TYPE="Region">Nation</ARGUMENT>
            </ARGUMENT-LIST>
        </OPERATION>
    </OPERATION-LIST>
</RISKCALC>"""


async def make_request(
    session: aiohttp.ClientSession, i: int, print_response: bool = False
) -> None:
    try:
        user_id = "rcloadtest" + str(i)
        print(f"Requesting with UserId: {user_id}")

        data = _data_xml(user_id)
        async with session.post(
            URL, headers=_headers(), data=data, ssl=False
        ) as response:
            print(f"Request {i}: Status {response.status}")
            if print_response:
                response_text = await response.text()
                print(f"Request {i}: Response {response_text}")
    except Exception as e:
        print(f"Request {i}: Failed with error {e}")


async def main(print_response: bool = False) -> None:
    async with aiohttp.ClientSession() as session:
        start_date = datetime.datetime.today()
        print(f"Request Process started @ {start_date}")
        tasks = [make_request(session, i, print_response) for i in range(1, 2)]
        await asyncio.gather(*tasks)
    print(
        f"Request Process started @ {start_date} and Completed @ {datetime.datetime.today()}"
    )


if __name__ == "__main__":
    asyncio.run(main(print_response=True))
