from __future__ import annotations

import os
import time

from auto_browser_client import AutoBrowserClient

BASE_URL = os.getenv("AUTO_BROWSER_BASE_URL", "http://127.0.0.1:8000")
TOKEN = os.getenv("AUTO_BROWSER_TOKEN")
QUERY = os.getenv("YOUTUBE_QUERY", "Shape of You Ed Sheeran")

SEARCH_INPUT_SELECTOR = 'input[name="search_query"]'
SEARCH_BUTTON_SELECTOR = "button#search-icon-legacy"
FIRST_VIDEO_SELECTOR = "ytd-video-renderer a#video-title"
CLICK_DELAY_SECONDS = 0.8
PAGE_LOAD_DELAY_SECONDS = 2.0
SEARCH_RESULTS_DELAY_SECONDS = 2.0


def _session_id(session: dict) -> str:
    session_id = session.get("id") or session.get("session_id")
    if not session_id:
        raise RuntimeError(f"Create session response missing id: {session}")
    return str(session_id)


def _click_optional(client: AutoBrowserClient, session_id: str, selector: str) -> None:
    try:
        client.click(session_id, selector=selector)
        time.sleep(CLICK_DELAY_SECONDS)
    except Exception:
        return


def main() -> None:
    with AutoBrowserClient(BASE_URL, token=TOKEN) as client:
        session = client.create_session(name="youtube-search", start_url="https://www.youtube.com")
        session_id = _session_id(session)

        time.sleep(PAGE_LOAD_DELAY_SECONDS)
        _click_optional(client, session_id, 'button:has-text("Accept all")')
        _click_optional(client, session_id, 'button:has-text("I agree")')

        client.type_text(session_id, QUERY, selector=SEARCH_INPUT_SELECTOR)
        client.click(session_id, selector=SEARCH_BUTTON_SELECTOR)

        time.sleep(SEARCH_RESULTS_DELAY_SECONDS)
        client.click(session_id, selector=FIRST_VIDEO_SELECTOR)

        takeover_url = session.get("takeover_url")
        print(f"Session id: {session_id}")
        if takeover_url:
            print(f"Takeover URL: {takeover_url}")
        print("Video should be playing in the session. Close it when you're done.")


if __name__ == "__main__":
    main()
