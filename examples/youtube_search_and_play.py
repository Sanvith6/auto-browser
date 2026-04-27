from __future__ import annotations

import os
import time

from auto_browser_client import AutoBrowserClient
from auto_browser_client.client import AutoBrowserError

BASE_URL = os.getenv("AUTO_BROWSER_BASE_URL", "http://127.0.0.1:8000")
TOKEN = os.getenv("AUTO_BROWSER_TOKEN")
QUERY = os.getenv("YOUTUBE_QUERY", "Shape of You Ed Sheeran")

SEARCH_INPUT_SELECTOR = 'input[name="search_query"]'
SEARCH_BUTTON_SELECTOR = "button#search-icon-legacy"
FIRST_VIDEO_SELECTOR = "ytd-video-renderer a#video-title"
POLL_INTERVAL_SECONDS = 0.5
PAGE_LOAD_TIMEOUT_SECONDS = 15
SEARCH_RESULTS_TIMEOUT_SECONDS = 15
VIDEO_LOAD_TIMEOUT_SECONDS = 15


def _session_id(session: dict) -> str:
    session_id = session.get("id") or session.get("session_id")
    if not session_id:
        raise RuntimeError(
            "Session response missing required id field (expected 'id' or 'session_id'): "
            f"{session}"
        )
    return str(session_id)


def _click_optional(client: AutoBrowserClient, session_id: str, selector: str) -> None:
    try:
        client.click(session_id, selector=selector)
    except AutoBrowserError as exc:
        if exc.status_code in {400, 404}:
            return
        raise


def _wait_for_url_contains(
    client: AutoBrowserClient,
    session_id: str,
    fragment: str,
    timeout_seconds: float,
) -> None:
    deadline = time.time() + timeout_seconds
    last_url = ""
    while time.time() < deadline:
        observation = client.observe(session_id, preset="fast")
        url = observation.get("url", "")
        last_url = url or last_url
        if fragment in url:
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"Timed out waiting for URL to include {fragment!r}. Last URL observed: {last_url!r}"
    )


def main() -> None:
    with AutoBrowserClient(BASE_URL, token=TOKEN) as client:
        session = client.create_session(name="youtube-search", start_url="https://www.youtube.com")
        session_id = _session_id(session)

        _wait_for_url_contains(client, session_id, "youtube.com", PAGE_LOAD_TIMEOUT_SECONDS)
        _click_optional(client, session_id, 'button:has-text("Accept all")')
        _click_optional(client, session_id, 'button:has-text("I agree")')

        client.type_text(session_id, QUERY, selector=SEARCH_INPUT_SELECTOR)
        client.click(session_id, selector=SEARCH_BUTTON_SELECTOR)

        _wait_for_url_contains(client, session_id, "results?search_query", SEARCH_RESULTS_TIMEOUT_SECONDS)
        client.click(session_id, selector=FIRST_VIDEO_SELECTOR)
        _wait_for_url_contains(client, session_id, "/watch", VIDEO_LOAD_TIMEOUT_SECONDS)

        takeover_url = session.get("takeover_url")
        print(f"Session id: {session_id}")
        if takeover_url:
            print(f"Takeover URL: {takeover_url}")
        print("Video should be playing in the session. Close it when you're done.")


if __name__ == "__main__":
    main()
