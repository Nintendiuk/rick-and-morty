import asyncio
import time

import httpx
from django.conf import settings
from httpx import AsyncClient

from characters.models import Character

GRAPHQL_QUERY = """
query {
  characters(page: %s) {
    info{
      pages
    }
    results{
      api_id: id
      name
      status
      species
      gender
      image
    }
  }
}
"""

MAX_CONCURRENT_REQUESTS = 1
MAX_RETRIES = 8
RETRY_DELAY_SECONDS = 5


def parse_characters_response(characters_response: dict) -> list[Character]:
    return [
        Character(**character_dict)
        for character_dict in characters_response["data"]["characters"]["results"]
    ]


async def post_with_retry(client: AsyncClient, url_to_scrape: str, page: int) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        response = await client.post(
            url_to_scrape, data={"query": GRAPHQL_QUERY % str(page)}
        )
        data = response.json()

        if "errors" in data:
            print(
                f"Page {page}: rate limited, retrying after "
                f"{RETRY_DELAY_SECONDS}s (attempt {attempt}/{MAX_RETRIES})"
            )
            await asyncio.sleep(RETRY_DELAY_SECONDS)
            continue

        return data

    raise RuntimeError(f"Page {page}: exceeded max retries due to rate limiting")


async def scrape_single_page(
    client: AsyncClient,
    url_to_scrape: str,
    page: int,
    semaphore: asyncio.Semaphore,
) -> list[Character]:
    async with semaphore:
        characters_response = await post_with_retry(client, url_to_scrape, page)
    return parse_characters_response(characters_response)


async def scrape_characters() -> list[Character]:
    start = time.perf_counter()

    url_to_scrape = settings.RICK_AND_MORTY_API_CHARACTERS_URL
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with httpx.AsyncClient() as client:
        characters_response = await post_with_retry(client, url_to_scrape, 1)
        num_pages = characters_response["data"]["characters"]["info"]["pages"]
        characters = parse_characters_response(characters_response)

        results = await asyncio.gather(
            *[
                scrape_single_page(client, url_to_scrape, page, semaphore)
                for page in range(2, num_pages + 1)
            ]
        )
        characters.extend(sum(results, []))

        end = time.perf_counter()
        print("Elapsed for scraping:", end - start)

        return characters


async def save_characters(characters: list[Character]) -> None:
    start = time.perf_counter()

    await Character.objects.abulk_create(characters, ignore_conflicts=True)

    end = time.perf_counter()
    print("Elapsed for saving:", end - start)


async def sync_characters_with_api() -> None:
    characters = await scrape_characters()
    await save_characters(characters)
