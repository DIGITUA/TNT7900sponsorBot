import json
from datetime import datetime, timezone # Added timezone for clarity

def convert_instagram_timestamp(media_id_str: str, epoch_ms: int) -> datetime:
    """
    Converts an Instagram media ID (which embeds a timestamp) to a datetime object.

    Args:
        media_id_str: The Instagram media ID as a string.
        epoch_ms: The epoch timestamp in milliseconds that Instagram uses for this ID type.
                  (e.g., for some older media IDs, it was 1314220021721 ms, which is approx. Aug 24, 2011)
                  However, modern Instagram media IDs (post-2017/Graph API) often use Unix epoch directly
                  or are represented differently. This function assumes the older right-shift mechanism.

    Returns:
        A datetime object representing the post time.
    """
    try:
        media_id_int = int(media_id_str) # Convert media_id string to integer
    except ValueError:
        print(f"Error: media_id '{media_id_str}' is not a valid integer.")
        # Return a placeholder or raise an error, depending on desired handling
        return datetime.min # Or handle more gracefully

    # The timestamp is often encoded in the higher bits of the media ID.
    # Right-shifting by 23 bits was a common method for older media IDs.
    # This extracts the custom timestamp part.
    custom_timestamp_ms = media_id_int >> 23
    
    # Add this custom timestamp to Instagram's specific epoch for these types of IDs.
    # The result is milliseconds since the standard Unix epoch (Jan 1, 1970).
    unix_timestamp_ms_calculated = custom_timestamp_ms + epoch_ms
    
    # Convert milliseconds to seconds for datetime.fromtimestamp
    unix_timestamp_sec = unix_timestamp_ms_calculated / 1000.0
    
    # Create a datetime object from the Unix timestamp.
    # It's good practice to make it timezone-aware (e.g., UTC) if the source is global.
    # If the epoch and calculation are assumed to be UTC.
    post_time = datetime.fromtimestamp(unix_timestamp_sec, tz=timezone.utc) # Make it UTC aware
    
    return post_time

def get_nested_value(data: dict, *keys: str):
    """
    Safely retrieves a nested value from a dictionary.

    Args:
        data: The dictionary to traverse.
        *keys: A sequence of keys representing the path to the desired value.

    Returns:
        The nested value if found, otherwise None.
    """
    current = data
    for key in keys:
        try:
            current = current[key]
        except (KeyError, TypeError, IndexError): # Added IndexError for lists
            return None # Key not found or current item is not subscriptable
    return current

def extract_post_captions_from_file(json_filename: str, output_filename: str, instagram_epoch_ms: int) -> list:
    """
    Extracts post captions (text) and associated post dates from an Instagram JSON data file
    and writes them to an output text file. The JSON is assumed to be a list of post objects.

    Args:
        json_filename: Path to the input JSON file containing Instagram post data.
        output_filename: Path to the output text file where results will be written.
        instagram_epoch_ms: The specific Instagram epoch in milliseconds for timestamp conversion.

    Returns:
        A list of dictionaries, where each dictionary contains 'caption' and 'timestamp'.
    """
    
    # Load the JSON data from the file
    try:
        with open(json_filename, "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        print(f"Error: Input JSON file '{json_filename}' not found.")
        return []
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{json_filename}'.")
        return []

    # Prepare a list to store the filtered results (captions and timestamps)
    captions_data = []

    # Open the output file to write results
    try:
        with open(output_filename, 'w', encoding='utf-8') as output_file:
            # Assuming 'data' is a list of post objects
            if not isinstance(data, list):
                print(f"Error: Expected a list of posts in '{json_filename}', but got {type(data)}.")
                return []

            for i, post in enumerate(data):
                if not isinstance(post, dict):
                    print(f"Warning: Item {i} in JSON data is not a dictionary, skipping.")
                    continue

                # Safely get the caption text
                # The path to caption text can vary, e.g., 'edge_media_to_caption', 'edges', 0, 'node', 'text'
                # Or more directly 'caption', 'text' as used here. Adjust if your JSON structure is different.
                caption_text = get_nested_value(post, 'caption', 'text') 
                
                # Also try another common path for captions in some Instagram data structures
                if not caption_text:
                     caption_node = get_nested_value(post, 'edge_media_to_caption', 'edges')
                     if caption_node and isinstance(caption_node, list) and len(caption_node) > 0:
                         caption_text = get_nested_value(caption_node[0], 'node', 'text')

                if caption_text:
                    media_id = post.get('pk', None)  # 'pk' is often the primary key or media ID.
                                                    # 'id' is another common field for media ID.
                    if not media_id:
                        media_id = post.get('id', None) 

                    timestamp_from_post = None
                    # Some Instagram JSON might contain a 'taken_at' or 'created_at' Unix timestamp directly
                    taken_at_unix = post.get('taken_at', None) # Unix timestamp in seconds
                    if taken_at_unix:
                        timestamp_from_post = datetime.fromtimestamp(taken_at_unix, tz=timezone.utc)
                    
                    # If direct timestamp not available, try converting from media_id
                    if not timestamp_from_post and media_id:
                        timestamp_from_post = convert_instagram_timestamp(str(media_id), instagram_epoch_ms)
                    elif not media_id:
                        print(f"Warning: Post {i} has caption but no 'pk' or 'id' field for timestamp derivation.")
                        # Use current time or a placeholder if no timestamp can be derived
                        timestamp_from_post = datetime.now(tz=timezone.utc) # Or None

                    if timestamp_from_post:
                        # Writing caption and timestamp to the file
                        output_file.write(f"Caption: {caption_text}\n")
                        # Format timestamp for better readability
                        output_file.write(f"Timestamp: {timestamp_from_post.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
                        output_file.write('-' * 40 + '\n')  # Separator between posts
                        
                        captions_data.append({
                            'caption': caption_text,
                            'timestamp': timestamp_from_post
                        })
                    else:
                        print(f"Warning: Could not determine timestamp for post with caption: '{caption_text[:50]}...'")
                else:
                    print(f"Info: Post {i} does not have a caption or caption text is empty.")
                    
    except IOError:
        print(f"Error: Could not write to output file '{output_filename}'.")
        return captions_data # Return what has been processed so far

    print(f"Data extraction complete. Results written to '{output_filename}'")
    return captions_data

# --- Example Usage ---
if __name__ == "__main__":
    input_json_file = "result.json"  # Name of the JSON file from the Instagram scraper
    output_text_file = "teamHistory.txt" # Name of the output text file
    
    # This epoch (1314220021721 ms) is specific to older Instagram media IDs (around August 2011).
    # If your 'result.json' comes from a modern API (like Graph API), the 'pk' or 'id' might not
    # use this epoch, or there might be a direct timestamp field (e.g., 'taken_at').
    # You may need to adjust this epoch or the timestamp extraction logic based on your JSON data source.
    # For modern Instagram data, often the 'taken_at' field (Unix timestamp in seconds) is available and preferred.
    instagram_media_id_epoch_ms = 1314220021721 

    print(f"Starting extraction from '{input_json_file}' to '{output_text_file}'...")
    extracted_data = extract_post_captions_from_file(input_json_file, output_text_file, instagram_media_id_epoch_ms)
    
    if extracted_data:
        print(f"Successfully extracted {len(extracted_data)} posts with captions.")
        # Example: print the first extracted item
        # print("First extracted item:", extracted_data[0])
    else:
        print("No data was extracted.")