import json
from datetime import datetime

def convert_instagram_timestamp(media_id, epoch):
    # Instagram's epoch (January 1st, 2011)
    INSTAGRAM_EPOCH = epoch
    
    # Extract timestamp by right-shifting 23 bits
    timestamp_ms = int(media_id) >> 23
    
    # Convert to Unix timestamp and then to datetime
    unix_timestamp = timestamp_ms + INSTAGRAM_EPOCH
    post_time = datetime.fromtimestamp(unix_timestamp / 1000)
    
    return post_time

def get_nested_value(data, *keys):
    current = data
    for key in keys:
        try:
            current = current[key]
        except (KeyError, TypeError):
            return None
    return current

def extract_post_captions_from_file(json_filename: str, output_filename: str):
    """Extract post captions (text) and associated post dates from a JSON file and write to an output text file."""
    
    # Load the JSON data from the file
    with open(json_filename, "r", encoding="utf-8") as file:
        data = json.load(file)

    # Prepare a list to store the filtered results
    captions_data = []

    # Open the output file to write results
    with open(output_filename, 'w', encoding='utf-8') as output_file:
        # Assuming 'data' is a list of posts
        for post in data:
            # Ensure 'caption' and 'text' keys exist in the post
            caption_text = get_nested_value(post, 'caption', 'text')
            if caption_text:
                media_id = post.get('pk', None)  # 'pk' is the media ID
                epoch = 1314220021721  # Instagram epoch or could be from post metadata
                if media_id:
                    timestamp = convert_instagram_timestamp(media_id, epoch)
                    # Writing caption and timestamp to the file
                    output_file.write(f"Caption: {caption_text}\n")
                    output_file.write(f"Timestamp: {timestamp}\n")
                    output_file.write('-' * 40 + '\n')  # Separator between posts
                    captions_data.append({
                        'caption': caption_text,
                        'timestamp': timestamp
                    })

    print(f"Data has been written to {output_filename}")
    return captions_data

# Usage
extract_post_captions_from_file("result.json", "teamHistory.txt")
