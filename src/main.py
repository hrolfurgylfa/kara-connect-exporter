import argparse
import json
import time
from dataclasses import dataclass
from os import environ
from typing import Any

import requests
from pydantic import BaseModel
from pydantic.type_adapter import TypeAdapter

ACCOUNTS_URL = "https://api.karaconnect.com/v2/identity/accounts/"
CLIENTS_URL = "https://api.karaconnect.com/v2/company/clients/"
SESSIONS_URL = "https://api.karaconnect.com/v1/professional/{account_id}/session/"

CLIENTS_FILE = "clients.json"
SESSIONS_FILE = "client_sessions.json"

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"

SLEEP_BETWEEN_REQUESTS_SECONDS = 1


class KaraConnectResponseFailed(Exception):
    def __init__(self, res_type: str, error_res: str) -> None:
        super().__init__(f"Kara connect {res_type} response failed: \n{error_res}")


class KaraConnectResponseMeta(BaseModel):
    page: int
    perPage: int
    total: int
    pages: int


class KaraConnectAccountsAccountResponse(BaseModel):
    id: int


class KaraConnectAccountsObjResponse(BaseModel):
    account: KaraConnectAccountsAccountResponse
    defaultAccount: bool


KaraConnectAccountsResponse = TypeAdapter(list[KaraConnectAccountsObjResponse])


@dataclass
class RequestData:
    bearer_token: str
    user_agent: str


def make_request(url: str, request_data: RequestData) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {request_data.bearer_token}",
        "User-Agent": request_data.user_agent,
    }
    response = requests.get(url, headers=headers)
    if response.ok:
        return response.json()
    else:
        raise KaraConnectResponseFailed(url, response.text)


def get_kara_connect_full_list(
    url: str, request_data: RequestData, data_key: str
) -> list[dict[str, Any]]:
    full_list: list[dict[str, Any]] = []

    page = 1
    pages = 1
    while True:
        next_url = f"{url}&page={page}" if "?" in url else f"{url}?page={page}"
        response = make_request(next_url, request_data)
        print(f"{url} page {page}")
        full_list.extend(response[data_key])
        meta = KaraConnectResponseMeta.model_validate(response["meta"])
        pages = meta.pages
        assert page == meta.page
        page += 1

        if page <= pages:
            time.sleep(SLEEP_BETWEEN_REQUESTS_SECONDS)
        else:
            break
    return full_list


def get_kara_connect_account_id(request_data: RequestData) -> int:
    response = KaraConnectAccountsResponse.validate_python(
        make_request(ACCOUNTS_URL, request_data)
    )
    for account in response:
        if account.defaultAccount:
            return account.account.id

    raise ValueError("No default account found")


def download_clients(request_data: RequestData) -> None:
    full_list = get_kara_connect_full_list(CLIENTS_URL, request_data, "client")
    with open(CLIENTS_FILE, "w") as f:
        json.dump(full_list, f)


def download_sessions(request_data: RequestData) -> None:
    account_id = get_kara_connect_account_id(request_data)

    with open(CLIENTS_FILE, "r") as f:
        clients = json.load(f)

    client_sessions: dict[int, list[dict[str, Any]]] = {}
    for i, client in enumerate(clients):
        client_id = client["id"]
        sessions_url = SESSIONS_URL.format(account_id=account_id)
        url = f"{sessions_url}?orderby=desc&expand=true&cid={client_id}"
        full_list = get_kara_connect_full_list(url, request_data, "session")
        client_sessions[client_id] = full_list

        # Skip sleep on the last client, since we're done
        if i < len(clients) - 1:
            time.sleep(SLEEP_BETWEEN_REQUESTS_SECONDS)

    with open(SESSIONS_FILE, "w") as f:
        json.dump(client_sessions, f)


def main():
    bearer_token = environ["KC_BEARER_TOKEN"].removeprefix("Bearer ")
    user_agent = environ.get("KC_USER_AGENT", DEFAULT_USER_AGENT)
    request_data = RequestData(bearer_token=bearer_token, user_agent=user_agent)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--clients",
        help="Download a list of all clients to clients.json",
        action="store_true",
    )
    parser.add_argument(
        "--sessions",
        help=(
            "Download a list of all sessions to sessions.json. "
            "Requires the list of clients in clients.json first."
        ),
        action="store_true",
    )
    args = parser.parse_args()
    if args.clients:
        download_clients(request_data)
    elif args.sessions:
        download_sessions(request_data)
    else:
        print("No action specified. Use --clients or --sessions.")


if __name__ == "__main__":
    main()
