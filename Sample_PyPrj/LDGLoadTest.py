import asyncio
import json
import os
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

from project_paths import resolve_project_relative

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


def _req(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise SystemExit(
            f"Missing required environment variable: {name}. See .env.example."
        )
    return v


async def upload_file_and_check_status() -> None:
    run_env = (os.getenv("LGD_RUN_ENV") or "").strip().lower()
    status_request_count = int(os.getenv("LGD_STATUS_REQUEST_COUNT", "500"))
    status_response_print_details = False

    if run_env == "qa":
        root_url = (
            "https://qa-api.losscalc.moodysanalytics.net/services/LossCalcBatch/LGD"
        )
        username = _req("LGD_BATCH_USERNAME_QA")
        password = _req("LGD_BATCH_PASSWORD_QA")
    else:
        root_url = "https://services.moodyskmv.com/services/LossCalcBatch/LGD"
        username = _req("LGD_BATCH_USERNAME_PROD")
        password = _req("LGD_BATCH_PASSWORD_PROD")

    upload_url = f"{root_url}/ProcessDelimitedFileAsync"
    status_url = f"{root_url}/GetBatchItems"

    file_path = resolve_project_relative(_req("LGD_UPLOAD_FILE_PATH"))
    file_name = _req("LGD_UPLOAD_FILE_NAME")

    async with aiohttp.ClientSession(
        auth=aiohttp.BasicAuth(username, password)
    ) as session:
        print("Uploading file...")
        with open(file_path, "rb") as file:
            form_data = aiohttp.FormData()
            form_data.add_field(
                name="files",
                value=file,
                filename=file_name,
                content_type="application/octet-stream",
            )

            async with session.post(upload_url, data=form_data) as upload_response:
                if upload_response.status >= 400:
                    print(
                        f"Failed to upload file: {upload_response.status} - "
                        f"{await upload_response.text()}"
                    )
                    return
                print("File uploaded successfully!")
                print("Upload Response:", await upload_response.text())
                uploaded_file_name = (await upload_response.json())[0]

        print(f"Making {status_request_count} concurrent status calls...")

        async def check_file_status() -> None:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Cache-Control": "no-cache",
            }
            async with session.get(status_url, headers=headers) as status_response:
                if status_response.status >= 400:
                    print(
                        f"Failed to retrieve file status: {status_response.status} - "
                        f"{await status_response.text()}"
                    )
                    return

                print("Status Response:", status_response.status)
                if status_response_print_details:
                    body = await status_response.text()
                    print("Status Response body:", body)
                    status_data = json.loads(body)
                    for item in status_data:
                        input_file = item.get("InputFile", {})
                        if input_file.get("FileName") == uploaded_file_name:
                            print(f"\nDetails for file '{uploaded_file_name}':")
                            print(json.dumps(item, indent=4))
                            break
                    else:
                        print(
                            f"File '{uploaded_file_name}' not found in the status response."
                        )

        await asyncio.gather(
            *[check_file_status() for _ in range(status_request_count)]
        )


if __name__ == "__main__":
    asyncio.run(upload_file_and_check_status())
