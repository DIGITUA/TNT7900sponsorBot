import json
import httpx  # Modern asynchronous HTTP client
from urllib.parse import quote  # For URL-encoding the variables dictionary
from typing import Optional, Dict, AsyncGenerator, Any # Added AsyncGenerator and Any for typing

# This is a specific GraphQL document ID for a particular Instagram query (user timeline/feed).
# These IDs can change if Instagram updates their internal API.
INSTAGRAM_ACCOUNT_DOCUMENT_ID = "9310670392322965" # Example, actual ID might vary or be deprecated

async def scrape_user_posts(
    username: str, 
    page_size: int = 12, 
    max_pages: Optional[int] = None
) -> AsyncGenerator[Dict[str, Any], None]: # Typing for async generator yielding dictionaries
    """
    Scrapes posts of an Instagram user given their username using an internal GraphQL endpoint.

    Note: Instagram's internal API, including GraphQL document IDs and request structures,
    can change without notice, which may break this scraper. This method is unofficial
    and relies on observing network requests from a web browser.
    Using such methods might be against Instagram's Terms of Service.

    Args:
        username: The Instagram username to scrape.
        page_size: Number of posts to fetch per page/request.
        max_pages: Maximum number of pages to scrape. If None, scrapes all available pages.

    Yields:
        A dictionary representing each post's node data.
    """
    base_url = "https://www.instagram.com/graphql/query" # Instagram's GraphQL endpoint
    
    # Variables for the GraphQL query. The structure of this dictionary is specific
    # to the query identified by INSTAGRAM_ACCOUNT_DOCUMENT_ID.
    variables = {
        "after": None,  # Cursor for pagination (points to the next page)
        "before": None, # Cursor for pagination (points to the previous page, not typically used for forward iteration)
        "data": { # Nested data specific to this query
            "count": page_size,
            "include_reel_media_seen_timestamp": True,
            "include_relationship_info": True,
            "latest_besties_reel_media": True, # Flags for what data to include
            "latest_reel_media": True
        },
        "first": page_size, # Number of items to fetch (equivalent to count for first page)
        "last": None, # For backward pagination
        "username": f"{username}", # The target username
        # These __relay_internal__ fields are often part of Instagram's internal request system (Relay framework)
        "__relay_internal__pv__PolarisIsLoggedInrelayprovider": False, # Changed to False, as public scraping usually isn't logged in
        "__relay_internal__pv__PolarisShareSheetV3relayprovider": False # Changed to False
    }

    prev_cursor = None  # To detect if pagination is stuck (no new cursor)
    _page_number = 0 # Track current page number

    # Use an asynchronous HTTP client session for efficient I/O
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0), # Set a timeout for requests
        # It's crucial to set appropriate headers, especially User-Agent,
        # and potentially others that Instagram expects (e.g., 'x-ig-app-id').
        # These might need to be obtained by inspecting browser requests.
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            # "x-ig-app-id": "YOUR_IG_APP_ID" # This might be required; find from browser's network tools
            "accept-language": "en-US,en;q=0.9",
        }
    ) as session:
        print(f"🚀 Starting scrape for user: {username}")
        while True:
            _page_number += 1
            if max_pages and _page_number > max_pages:
                print(f"🏁 Reached max_pages limit ({max_pages}). Stopping scrape.")
                break
            
            print(f"📄 Scraping page {_page_number} for {username} (Cursor: {variables.get('after')})")

            # The GraphQL query parameters are typically sent as URL-encoded form data.
            # 'variables' is JSON-stringified and then URL-quoted. 'doc_id' is the query identifier.
            form_data_payload = f"variables={quote(json.dumps(variables, separators=(',', ':')))}&doc_id={INSTAGRAM_ACCOUNT_DOCUMENT_ID}"

            try:
                response = await session.post(
                    base_url,
                    data=form_data_payload,
                    # Ensure the content-type header is set as expected by Instagram's endpoint
                    headers={"content-type": "application/x-www-form-urlencoded"}
                )
                response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
                data = response.json() # Parse the JSON response
            except httpx.HTTPStatusError as e:
                print(f"❌ HTTP error during request for page {_page_number} of {username}: {e.response.status_code} - {e.response.text}")
                break # Stop on HTTP error
            except httpx.RequestError as e:
                print(f"❌ Request error for page {_page_number} of {username}: {e}")
                break # Stop on other request errors (timeout, connection error)
            except json.JSONDecodeError:
                print(f"❌ Failed to decode JSON response for page {_page_number} of {username}. Content: {response.text[:200]}")
                break

            # Save the raw JSON response for debugging or further analysis (optional)
            # Consider making this conditional or naming files uniquely per page/user.
            # with open(f"debug_page_{_page_number}_{username}.json", "w", encoding="utf-8") as f:
            #    json.dump(data, f, indent=2, ensure_ascii=False)

            # Navigate through the JSON response to find the list of posts.
            # The path 'data.xdt_api__v1__feed__user_timeline_graphql_connection.edges' is specific to this query.
            # It might change. Using jmespath or careful nested gets is advisable for robustness.
            try:
                # Using jmespath for safer and more readable nested data extraction
                # posts_connection = data.get("data", {}).get("xdt_api__v1__feed__user_timeline_graphql_connection", {})
                posts_connection_path = "data.xdt_api__v1__feed__user_timeline_graphql_connection"
                posts_connection = jmespath.search(posts_connection_path, data)

                if not posts_connection:
                    print(f"⚠️ Could not find '{posts_connection_path}' in response for {username} on page {_page_number}. Data: {str(data)[:500]}")
                    if data.get("message") == "rate limited": # Check for explicit rate limit message
                        print("🚫 Rate limited by Instagram. Stopping.")
                    break
                
                post_edges = posts_connection.get("edges", [])
                if not post_edges and _page_number == 1: # No posts found on the first page
                    print(f"ℹ️ No posts found for user '{username}' or profile might be private/restricted.")
                    break
                
                for post_edge in post_edges:
                    if post_edge and "node" in post_edge:
                        yield post_edge["node"] # Yield the actual post data
                    else:
                        print(f"Warning: Post edge missing 'node': {post_edge}")


                page_info = posts_connection.get("page_info", {})
                if not page_info.get("has_next_page"):
                    print(f"🏁 No more pages to scrape for {username}. Reached the end.")
                    break

                current_end_cursor = page_info.get("end_cursor")
                if not current_end_cursor or current_end_cursor == prev_cursor:
                    print(f"⚠️ Pagination cursor did not change or is missing. Possible end or issue. Cursor: {current_end_cursor}")
                    break # Avoid infinite loops if cursor doesn't change

                prev_cursor = current_end_cursor
                variables["after"] = current_end_cursor # Set cursor for the next page

            except KeyError as e:
                print(f"❌ KeyError accessing data for {username} on page {_page_number}: {e}. Response structure might have changed.")
                print(f"   Response snippet: {str(data)[:500]}")
                break
            except Exception as e:
                print(f"❌ An unexpected error occurred while processing page {_page_number} for {username}: {e}")
                break
            
            # Optional: Add a small delay between requests to be polite to the server
            # await asyncio.sleep(random.uniform(1, 3)) # e.g., 1-3 seconds

    print(f"✅ Finished scraping for user: {username}")


# --- Example of how to run the scraper ---
if __name__ == "__main__":
    import asyncio
    import random # For potential delays

    async def run_scraper():
        target_username = "trialnterror7900" # Replace with the desired Instagram username
        max_pages_to_scrape = 3  # Set a limit for the number of pages, or None for all
        
        all_posts_data = []
        # Asynchronously iterate through the posts yielded by the scraper
        async for post_data in scrape_user_posts(target_username, max_pages=max_pages_to_scrape):
            all_posts_data.append(post_data)
            # print(f"Retrieved post ID: {post_data.get('id', 'N/A')}") # Example: print post ID

        if all_posts_data:
            # Save the collected post data to a JSON file
            output_filename = "result.json" # Name for the output file
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(all_posts_data, f, indent=2, ensure_ascii=False)
            print(f"\n💾 Saved {len(all_posts_data)} posts to '{output_filename}'")
        else:
            print(f"\nNo posts were retrieved for '{target_username}'.")

    # Run the asynchronous main function
    asyncio.run(run_scraper())