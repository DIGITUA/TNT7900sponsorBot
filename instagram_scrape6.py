import json
import httpx
from urllib.parse import quote
from typing import Optional
from typing import Dict
import jmespath

INSTAGRAM_ACCOUNT_DOCUMENT_ID = "9310670392322965"

async def scrape_user_posts(username: str, page_size=12, max_pages: Optional[int] = None):
    """Scrape all posts of an Instagram user given the username."""
    base_url = "https://www.instagram.com/graphql/query"
    variables = {
        "after": None,
        "before": None,
        "data": {
            "count": page_size,
            "include_reel_media_seen_timestamp": True,
            "include_relationship_info": True,
            "latest_besties_reel_media": True,
            "latest_reel_media": True
        },
        "first": page_size,
        "last": None,
        "username": f"{username}",
        "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
        "__relay_internal__pv__PolarisShareSheetV3relayprovider": True
    }

    prev_cursor = None
    _page_number = 1

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as session:
        while True:
            body = f"variables={quote(json.dumps(variables, separators=(',', ':')))}&doc_id={INSTAGRAM_ACCOUNT_DOCUMENT_ID}"

            response = await session.post(
                base_url,
                data=body,
                headers={"content-type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            data = response.json()

            with open("ts2.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            posts = data["data"]["xdt_api__v1__feed__user_timeline_graphql_connection"]
            for post in posts["edges"]:
                yield post["node"]

            page_info = posts["page_info"]
            if not page_info["has_next_page"]:
                print(f"scraping posts page {_page_number}")
                break

            if page_info["end_cursor"] == prev_cursor:
                print("found no new posts, breaking")
                break

            prev_cursor = page_info["end_cursor"]
            variables["after"] = page_info["end_cursor"]
            _page_number += 1

            if max_pages and _page_number > max_pages:
                break

# Example run:
if __name__ == "__main__":
    import asyncio

    async def main():
        posts = [post async for post in scrape_user_posts("trialnterror7900", max_pages=3)]

        # save a JSON file
        with open("result.json", "w",encoding="utf-8") as f:
            json.dump(posts, f, indent=2, ensure_ascii=False)
        #print(json.dumps(posts, indent=2, ensure_ascii=False))

    asyncio.run(main())