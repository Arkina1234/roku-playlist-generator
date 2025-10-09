import logging
import requests

def format_extinf(channel_id, tvg_id, tvg_chno, tvg_name, tvg_logo, group_title, display_name):
    """Formats the #EXTINF line."""
    # Ensure tvg_chno is empty if None or invalid
    chno_str = str(tvg_chno) if tvg_chno is not None and str(tvg_chno).isdigit() else ""

    # Basic sanitization for names/titles within the M3U format
    sanitized_tvg_name = tvg_name.replace('"', "'") if tvg_name else ""
    sanitized_group_title = group_title.replace('"', "'") if group_title else ""
    sanitized_display_name = display_name.replace(',', '') if display_name else ""  # Commas break the EXTINF line itself

    return (f'#EXTINF:-1 '
            f'channel-id="{channel_id}" '
            f'tvg-id="{tvg_id}" '
            f'tvg-chno="{chno_str}" '
            f'tvg-name="{sanitized_tvg_name}" '
            f'tvg-logo="{tvg_logo}" '
            f'group-title="{sanitized_group_title}",'
            f'{sanitized_display_name}\n')

def fetch_url(url, is_json=True, is_gzipped=False):
    """Fetch URL content with error handling."""
    try:
        headers = {}
        if is_gzipped:
            headers['Accept-Encoding'] = 'gzip'
            
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        if is_json:
            return response.json()
        return response.text
    except Exception as e:
        logging.error(f"Failed to fetch {url}: {e}")
        return None

def write_m3u_file(filename, content):
    """Write M3U content to file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        logging.info(f"Successfully wrote {filename}")
    except Exception as e:
        logging.error(f"Failed to write {filename}: {e}")

def get_roku_stream_url(channel_id):
    """Get the actual stream URL for a Roku channel."""
    try:
        # First, get the channel data
        content_url = f"https://therokuchannel.roku.com/api/v2/homescreen/content/https%3A%2F%2Fcontent.sr.roku.com%2Fcontent%2Fv1%2Froku-trc%2F{channel_id}%3Fexpand%3DviewOptions.channelId%252CviewOptions.playId%252Cnext.viewOptions.channelId%252Cnext.viewOptions.playId%26featureInclude%3Dbookmark%252Cwatchlist%252ClinearSchedule"
        
        # Get CSRF token first (simplified - you may need to adjust this)
        session = requests.Session()
        csrf_response = session.get("https://therokuchannel.roku.com/")
        csrf_token = None
        
        # Extract CSRF token from headers or cookies (this is simplified)
        if 'csrf-token' in csrf_response.headers:
            csrf_token = csrf_response.headers['csrf-token']
        
        # Get playback URL
        playback_url = "https://therokuchannel.roku.com/api/v3/playback"
        headers = {
            "content-type": "application/json",
        }
        if csrf_token:
            headers["csrf-token"] = csrf_token
            
        playback_data = {
            "rokuId": channel_id,
            "playId": "live",  # This would need to be extracted from the content API
            "mediaFormat": "m3u",
            "drmType": "widevine", 
            "quality": "fhd",
            "bifUrl": None,
            "adPolicyId": "",
            "providerId": "rokuavod"
        }
        
        playback_response = session.post(playback_url, json=playback_data, headers=headers)
        if playback_response.status_code == 200:
            playback_info = playback_response.json()
            stream_url = playback_info.get('url', '')
            
            # Transform the URL if needed
            if 'osm.sr.roku.com' in stream_url:
                stream_url = stream_url.replace('https://osm.sr.roku.com/', 'https://aka-live491.delivery.roku.com/')
                stream_url = stream_url.replace('/live.m3u8', '/t2-origin/out/v1/live.m3u8')
            
            return stream_url
            
    except Exception as e:
        logging.error(f"Failed to get stream URL for channel {channel_id}: {e}")
    
    # Fallback to a template if the API call fails
    return f"https://aka-live491.delivery.roku.com/{channel_id}/t2-origin/out/v1/live.m3u8"

def generate_roku_playlist(sort='chno'):
    """Generates M3U playlist for Roku."""
    ROKU_URL = 'https://i.mjh.nz/Roku/.channels.json'
    EPG_URL = 'https://github.com/matthuisman/i.mjh.nz/raw/master/Roku/all.xml.gz'

    logging.info("--- Generating Roku playlist ---")
    data = fetch_url(ROKU_URL, is_json=True, is_gzipped=True)
    if not data or 'channels' not in data:
        logging.error("Failed to fetch or parse Roku data.")
        return

    output_lines = [f'#EXTM3U url-tvg="{EPG_URL}"\n']
    channels_to_process = data.get('channels', {})

    # Sort channels
    try:
        if sort == 'chno':
            sorted_channel_ids = sorted(channels_to_process.keys(), 
                                     key=lambda k: int(channels_to_process[k].get('chno', 99999)))
        else:  # Default to name sort
            sorted_channel_ids = sorted(channels_to_process.keys(), 
                                     key=lambda k: channels_to_process[k].get('name', '').lower())
    except Exception as e:
        logging.warning(f"Sorting failed for Roku, using default order. Error: {e}")
        sorted_channel_ids = list(channels_to_process.keys())

    # Build M3U entries
    for channel_id in sorted_channel_ids:
        channel = channels_to_process[channel_id]
        chno = channel.get('chno')
        name = channel.get('name', 'Unknown Channel')
        logo = channel.get('logo', '')
        groups_list = channel.get('groups', [])
        group_title = groups_list[0] if groups_list else 'Uncategorized'
        tvg_id = channel_id  # Roku IDs seem unique enough

        extinf = format_extinf(channel_id, tvg_id, chno, name, logo, group_title, name)
        stream_url = get_roku_stream_url(channel_id)
        
        output_lines.append(extinf)
        output_lines.append(stream_url + '\n')

    write_m3u_file("roku_all.m3u", "".join(output_lines))

# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate_roku_playlist()