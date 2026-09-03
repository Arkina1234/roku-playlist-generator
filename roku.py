import requests
import json
import urllib.parse
import re
import time
from typing import Optional, Dict, List

class RokuChannelExtractor:
    def __init__(self):
        self.api_url = 'https://therokuchannel.roku.com/api/v2/homescreen/content/'
        self.playback_url = 'https://therokuchannel.roku.com/api/v3/playback'
        self.epg_url = './epg.json'
        self.csrf_url = 'https://therokuchannel.roku.com/api/v1/csrf'
        self.base_url = "https://content.sr.roku.com/content/v1/roku-trc/"
        
        self.session = requests.Session()
        
        # More comprehensive headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
        })
        
        # Get initial cookies by visiting the main site
        self._initialize_session()

    def _initialize_session(self):
        """Initialize session with cookies from main site"""
        try:
            # Visit main Roku channel page to get cookies
            main_url = 'https://therokuchannel.roku.com/'
            response = self.session.get(main_url, timeout=10)
            response.raise_for_status()
            
            # Also visit a watch page to get additional cookies
            watch_url = 'https://therokuchannel.roku.com/watch/'
            self.session.get(watch_url, timeout=10)
            
            time.sleep(0.1)  # Small delay to avoid rate limiting
            print("Session initialized successfully")
        except Exception as e:
            print(f"Warning: Could not initialize session: {e}")

    def _make_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make HTTP request with retry logic"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Add a small delay between requests
                if attempt > 0.1:
                    time.sleep(retry_delay * attempt)
                
                # Always add a random referer
                if 'headers' not in kwargs:
                    kwargs['headers'] = {}
                
                # Ensure we have the right headers for each request
                if 'csrf-token' not in kwargs['headers'] and 'csrf_token' in kwargs:
                    kwargs['headers']['csrf-token'] = kwargs.pop('csrf_token')
                
                # Add common headers
                kwargs['headers'].setdefault('Accept', 'application/json, text/plain, */*')
                kwargs['headers'].setdefault('Accept-Language', 'en-US,en;q=0.9')
                
                response = self.session.request(method, url, timeout=30, **kwargs)
                
                # If we get a 403, try refreshing the session
                if response.status_code == 403:
                    print(f"Got 403, refreshing session (attempt {attempt + 1})...")
                    self._initialize_session()
                    continue
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                print(f"Request failed (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    raise
                continue
        
        return None

    def get_epg_data(self) -> Optional[Dict]:
        """Fetch EPG data from Roku"""
        try:
            response = self._make_request('GET', self.epg_url)
            if response:
                return response.json()
            return None
        except Exception as e:
            print(f"Error fetching EPG: {e}")
            return None

    def get_csrf_token(self) -> Optional[str]:
        """Fetch CSRF token"""
        try:
            # First, get a new CSRF token
            response = self._make_request('GET', self.csrf_url)
            if response:
                csrf_token = response.json().get('csrf')
                if csrf_token:
                    # Store it for future requests
                    self.session.headers['csrf-token'] = csrf_token
                    return csrf_token
            return None
        except Exception as e:
            print(f"Error fetching CSRF: {e}")
            return None

    def get_content(self, channel_id: str) -> Optional[Dict]:
        """Fetch content data for a specific channel"""
        # Build the URL with proper encoding
        encoded_url = urllib.parse.quote(self.base_url, safe='')
        encoded_query = urllib.parse.quote("?expand=", safe='')
        params = "viewOptions.channelId,viewOptions.playId,next.viewOptions.channelId,next.viewOptions.playId"
        encoded_params = urllib.parse.quote(params, safe='')
        double_encoded_params = encoded_params.replace('%2C', '%252C')
        
        content_url = f"{self.api_url}{encoded_url}{channel_id}{encoded_query}{double_encoded_params}"
        
        try:
            headers = {
                'Referer': f'https://therokuchannel.roku.com/watch/{channel_id}',
                'Origin': 'https://therokuchannel.roku.com',
            }
            response = self._make_request('GET', content_url, headers=headers)
            if response:
                return response.json()
            return None
        except Exception as e:
            print(f"Error fetching content for {channel_id}: {e}")
            return None

    def get_playback(self, channel_id: str, play_id: str, media_type: str, csrf_token: str) -> Optional[Dict]:
        """Get playback URL and license server"""
        # Determine media format
        media_format = 'mpeg-dash' if media_type == 'DASH' else 'm3u'
        
        json_data = {
            "rokuId": channel_id,
            "playId": play_id,
            "mediaFormat": media_format,
            "drmType": "widevine",
            "quality": "fhd",
            "bifUrl": None,
            "adPolicyId": "",
            "providerId": "rokuavod"
        }
        
        headers = {
            'Referer': f'https://therokuchannel.roku.com/watch/{channel_id}',
            'Origin': 'https://therokuchannel.roku.com',
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/plain, */*',
        }
        
        try:
            # Always get a fresh CSRF token for this request
            current_csrf = self.get_csrf_token()
            if current_csrf:
                headers['csrf-token'] = current_csrf
            
            response = self._make_request(
                'POST', 
                self.playback_url, 
                json=json_data, 
                headers=headers
            )
            
            if response:
                return response.json()
            return None
        except Exception as e:
            print(f"Error getting playback for {channel_id}: {e}")
            return None

    def process_stream_url(self, url: str, media_type: str) -> str:
        """Process and clean stream URL"""
        if not url:
            return ""
            
        if media_type == 'DASH':
            # Remove query parameters
            return url.split('?')[0]
        else:  # HLS
            # Replace various domain patterns
            replacements = {
                'https://osm.sr.roku.com/osm/v1/hls/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm-use1.sr.roku.com/osm/v1/hls/use1/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm-use2.sr.roku.com/osm/v1/hls/use2/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm-euw1.sr.roku.com/osm/v1/hls/euw1/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm-aps1.sr.roku.com/osm/v1/hls/aps1/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm.sr.roku.com/osm/v1/hls/': 'https://aka-live1050.delivery.roku.com/'
            }
            
            for old, new in replacements.items():
                if old in url:
                    url = url.replace(old, new)
                    break
            
            # Replace /live.m3u8 with /t2-origin/out/v1/live.m3u8
            url = url.replace('/live.m3u8', '/t2-origin/out/v1/live.m3u8')
            
            # Remove query parameters
            return url.split('?')[0]

    def generate_m3u(self, output_file: str = "roku_channels.m3u"):
        """Generate M3U playlist"""
        print("Fetching EPG data...")
        epg_data = self.get_epg_data()
        if not epg_data:
            print("Failed to get EPG data")
            return

        print("Getting CSRF token...")
        csrf_token = self.get_csrf_token()
        if not csrf_token:
            print("Failed to get CSRF token")
            return

        # Prepare M3U content
        m3u_lines = [
            '#EXTM3U url-tvg="https://github.com/matthuisman/i.mjh.nz/raw/master/Roku/all.xml"'
        ]

        # Process each channel
        channels = []
        collections = epg_data.get('collections', [])
        print(f"Found {len(collections)} channels in EPG")
        
        for idx, collection in enumerate(collections, 1):
            station = collection.get('features', {}).get('station', {})
            if not station:
                continue

            channel_id = station.get('meta', {}).get('id')
            title = station.get('title', 'Unknown')
            display_number = station.get('displayNumber')
            
            if not channel_id:
                continue

            print(f"Processing channel {idx}/{len(collections)}: {title} ({channel_id})")
            
            # Get content data
            content_data = self.get_content(channel_id)
            if not content_data:
                continue

            # Extract playId and video type
            view_options = content_data.get('viewOptions', [])
            if not view_options:
                print(f"No viewOptions for {channel_id}")
                continue

            play_id = view_options[0].get('playId')
            if not play_id:
                print(f"No playId for {channel_id}")
                continue

            # Get video type (try first video, then second)
            videos = view_options[0].get('media', {}).get('videos', [])
            video_type = None
            for video in videos[:2]:  # Check first two videos
                if video.get('videoType'):
                    video_type = video.get('videoType')
                    break

            if not video_type:
                print(f"No video type found for {channel_id}")
                continue

            # Get playback data
            playback_data = self.get_playback(channel_id, play_id, video_type, csrf_token)
            if not playback_data:
                continue

            stream_url = playback_data.get('url')
            if not stream_url:
                continue

            # Process stream URL
            processed_url = self.process_stream_url(stream_url, video_type)
            if not processed_url:
                continue

            # Get license server for DASH
            license_server = None
            if video_type == 'DASH':
                license_server = playback_data.get('drm', {}).get('widevine', {}).get('licenseServer')

            # Store channel data
            channels.append({
                'id': channel_id,
                'title': title,
                'display_number': display_number,
                'stream_url': processed_url,
                'license_server': license_server,
                'video_type': video_type
            })
            
            print(f"✓ Added {title} (Type: {video_type})")
            time.sleep(0.1)  # Rate limiting delay

        # Sort channels by display number (100-9999)
        channels.sort(key=lambda x: int(x['display_number']) if x['display_number'] and 100 <= int(x['display_number']) <= 9999 else 9999)

        print(f"\nWriting {len(channels)} channels to {output_file}")
        
        # Write M3U file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(m3u_lines))
            f.write('\n')
            
            for channel in channels:
                # Add EXTINF line
                f.write(
                    f'#EXTINF:-1 channel-id="{channel["id"]}" '
                    f'tvg-id="{channel["id"]}" '
                    f'tvg-chno="{channel["display_number"]}" '
                    f'tvg-name="" tvg-logo="" group-title="",{channel["title"]}\n'
                )

                # Add KODIPROP for DASH with Widevine
                if channel['video_type'] == 'DASH' and channel['license_server']:
                    f.write('#KODIPROP:inputstreamaddon=inputstream.adaptive\n')
                    f.write('#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha\n')
                    f.write(
                        f'#KODIPROP:inputstream.adaptive.license_key='
                        f'{channel["license_server"]}|Content-Type=application/octet-stream|R{{SSM}}|\n'
                    )

                # Add stream URL
                f.write(f'{channel["stream_url"]}\n\n')

        print(f"✓ M3U playlist saved to {output_file}")


if __name__ == "__main__":
    extractor = RokuChannelExtractor()
    extractor.generate_m3u("roku_drm.m3u")