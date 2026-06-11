from celery import shared_task

from characters.scraper import sync_characters_with_api


@shared_task
def run_sync_with_api() -> None:
    sync_characters_with_api()
