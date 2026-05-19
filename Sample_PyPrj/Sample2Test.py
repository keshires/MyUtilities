import asyncio
import aiohttp
import nest_asyncio

# Patch event loop if already running (e.g., in Jupyter)
nest_asyncio.apply()

URL = 'https://qa.riskcalc.moodysanalytics.net/Token'
DATA = {
        "username": "rcotest",
        "password": "rcotest"
    }

async def make_request(session, i, print_response=False):
    try:
        async with session.post(URL, data=DATA) as response:
            print(f"Request {i}: Status {response.status}")
            if print_response:
                response_text = await response.text()
                print(f"Request {i}: Response {response_text}")
    except Exception as e:
        print(f"Request {i}: Failed with error {e}")

async def main(print_response=False):
    async with aiohttp.ClientSession() as session:
        tasks = [make_request(session, i, print_response) for i in range(1, 950)]
        await asyncio.gather(*tasks)

# Run the event loop safely
loop = asyncio.get_event_loop()
loop.run_until_complete(main(print_response=False))  # Set to False to suppress response body