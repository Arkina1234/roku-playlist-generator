#!/usr/bin/env python3
"""
Roku Channel M3U Generator
Generates an M3U playlist from Roku channels with Widevine DRM support
"""

import requests
import json
import urllib.parse
import time
import re
from typing import Optional, Dict, List, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

class RokuChannelExtractor:
    """Main class to extract and generate Roku channel playlists"""
    
    def __init__(self):
        # API endpoints
        self.api_url = 'https://therokuchannel.roku.com/api/v2/homescreen/content/'
        self.playback_url = 'https://therokuchannel.roku.com/api/v3/playback'
        self.epg_url = 'https://therokuchannel.roku.com/api/v2/epg'
        self.csrf_url = 'https://therokuchannel.roku.com/api/v1/csrf'
        self.base_url = "https://content.sr.roku.com/content/v1/roku-trc/"
        
        # Setup session with headers
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })
        
        # Statistics
        self.stats = {
            'total': 0,
            'processed': 0,
            'failed': 0,
            'success': 0
        }

    def _make_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """
        Make HTTP request with retry logic and error handling
        """
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                # Set default timeout
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = 15
                
                # Add basic headers if not present
                if 'headers' not in kwargs:
                    kwargs['headers'] = {}
                
                # Ensure we have a referer
                if 'Referer' not in kwargs['headers'] and 'referer' not in kwargs['headers']:
                    kwargs['headers']['Referer'] = 'https://therokuchannel.roku.com/'
                
                # Make the request
                response = self.session.request(method, url, **kwargs)
                
                # If 403, try with different user agent
                if response.status_code == 403:
                    if attempt < max_retries - 1:
                        # Try alternative user agent
                        alt_headers = {
                            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
                        }
                        kwargs['headers'].update(alt_headers)
                        time.sleep(retry_delay)
                        continue
                    else:
                        response.raise_for_status()
                
                # Check if response is valid JSON for API calls
                if 'application/json' in response.headers.get('Content-Type', ''):
                    try:
                        response.json()
                    except:
                        print(f"Invalid JSON response from {url}")
                        return None
                
                return response
                
            except requests.exceptions.RequestException as e:
                print(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                return None
            except Exception as e:
                print(f"Unexpected error: {e}")
                return None
        
        return None

    def get_epg_data(self) -> Optional[Dict]:
        """
        Fetch EPG (Electronic Program Guide) data from Roku
        """
        print("📡 Fetching EPG data...")
        response = self._make_request('GET', self.epg_url)
        if response:
            try:
                data = response.json()
                print(f"✅ EPG data fetched successfully")
                return data
            except:
                print("❌ Failed to parse EPG data")
        return None

    def get_csrf_token(self) -> Optional[str]:
        """
        Fetch CSRF token required for playback requests
        """
        print("🔑 Fetching CSRF token...")
        response = self._make_request('GET', self.csrf_url)
        if response:
            try:
                data = response.json()
                csrf_token = data.get('csrf')
                if csrf_token:
                    print("✅ CSRF token obtained")
                    return csrf_token
            except:
                print("❌ Failed to get CSRF token")
        return None

    def get_channel_content(self, channel_id: str) -> Optional[Dict]:
        """
        Fetch content data for a specific channel
        """
        # Build the URL with proper encoding
        encoded_base = urllib.parse.quote(self.base_url, safe='')
        params = "viewOptions.channelId,viewOptions.playId,next.viewOptions.channelId,next.viewOptions.playId"
        encoded_params = urllib.parse.quote(params, safe='')
        double_encoded_params = encoded_params.replace('%2C', '%252C')
        
        content_url = f"{self.api_url}{encoded_base}{channel_id}?expand={double_encoded_params}"
        
        headers = {
            'Referer': f'https://therokuchannel.roku.com/watch/{channel_id}',
            'Origin': 'https://therokuchannel.roku.com',
        }
        
        response = self._make_request('GET', content_url, headers=headers)
        if response:
            try:
                return response.json()
            except:
                pass
        return None

    def get_playback_data(self, channel_id: str, play_id: str, media_type: str, csrf_token: str) -> Optional[Dict]:
        """
        Get playback URL and license server information
        """
        # Determine media format
        media_format = 'mpeg-dash' if media_type.upper() == 'DASH' else 'm3u'
        
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
            'csrf-token': csrf_token
        }
        
        response = self._make_request('POST', self.playback_url, json=json_data, headers=headers)
        if response:
            try:
                return response.json()
            except:
                pass
        return None

    def process_stream_url(self, url: str, media_type: str) -> str:
        """
        Process and clean stream URL
        """
        if not url:
            return ""
        
        # Remove query parameters
        url = url.split('?')[0]
        
        if media_type.upper() == 'HLS':
            # Replace domain patterns for HLS streams
            domain_replacements = {
                'https://osm.sr.roku.com/osm/v1/hls/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm-use1.sr.roku.com/osm/v1/hls/use1/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm-use2.sr.roku.com/osm/v1/hls/use2/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm-euw1.sr.roku.com/osm/v1/hls/euw1/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm-aps1.sr.roku.com/osm/v1/hls/aps1/master/': 'https://aka-live1050.delivery.roku.com/',
                'https://osm.sr.roku.com/osm/v1/hls/': 'https://aka-live1050.delivery.roku.com/'
            }
            
            for old, new in domain_replacements.items():
                if old in url:
                    url = url.replace(old, new)
                    break
            
            # Replace live.m3u8 with t2-origin path
            url = url.replace('/live.m3u8', '/t2-origin/out/v1/live.m3u8')
        
        return url

    def process_channel(self, channel_info: Dict, csrf_token: str) -> Optional[Dict]:
        """
        Process a single channel (for parallel execution)
        """
        channel_id = channel_info['id']
        title = channel_info['title']
        display_number = channel_info.get('display_number', '0')
        
        try:
            # Get content data
            content_data = self.get_channel_content(channel_id)
            if not content_data:
                self.stats['failed'] += 1
                return None

            # Extract playId and video type
            view_options = content_data.get('viewOptions', [])
            if not view_options:
                self.stats['failed'] += 1
                return None

            play_id = view_options[0].get('playId')
            if not play_id:
                self.stats['failed'] += 1
                return None

            # Get video type (try first two videos)
            videos = view_options[0].get('media', {}).get('videos', [])
            video_type = None
            for video in videos[:2]:
                if video.get('videoType'):
                    video_type = video.get('videoType')
                    break

            if not video_type:
                self.stats['failed'] += 1
                return None

            # Get playback data
            playback_data = self.get_playback_data(channel_id, play_id, video_type, csrf_token)
            if not playback_data:
                self.stats['failed'] += 1
                return None

            stream_url = playback_data.get('url')
            if not stream_url:
                self.stats['failed'] += 1
                return None

            # Process stream URL
            processed_url = self.process_stream_url(stream_url, video_type)
            if not processed_url:
                self.stats['failed'] += 1
                return None

            # Get license server for DASH
            license_server = None
            if video_type.upper() == 'DASH':
                license_server = playback_data.get('drm', {}).get('widevine', {}).get('licenseServer')

            self.stats['success'] += 1
            
            return {
                'id': channel_id,
                'title': title,
                'display_number': display_number,
                'stream_url': processed_url,
                'license_server': license_server,
                'video_type': video_type.upper()
            }
            
        except Exception as e:
            print(f"❌ Error processing {title}: {e}")
            self.stats['failed'] += 1
            return None

    def generate_m3u(self, output_file: str = "roku_channels.m3u", max_workers: int = 5):
        """
        Generate M3U playlist with parallel processing
        """
        start_time = time.time()
        
        print("\n" + "="*60)
        print("🎬 ROKU CHANNEL M3U GENERATOR")
        print("="*60 + "\n")
        
        # Get EPG data
        epg_data = self.get_epg_data()
        if not epg_data:
            print("❌ Failed to get EPG data. Exiting.")
            return

        # Get CSRF token
        csrf_token = self.get_csrf_token()
        if not csrf_token:
            print("❌ Failed to get CSRF token. Exiting.")
            return

        # Extract channels from EPG
        channels = []
        for collection in epg_data.get('collections', []):
            station = collection.get('features', {}).get('station', {})
            if station:
                channel_id = station.get('meta', {}).get('id')
                title = station.get('title', 'Unknown')
                display_number = station.get('displayNumber')
                
                if channel_id and display_number and 100 <= int(display_number) <= 9999:
                    channels.append({
                        'id': channel_id,
                        'title': title,
                        'display_number': display_number
                    })

        self.stats['total'] = len(channels)
        print(f"\n📺 Found {self.stats['total']} channels")
        print(f"⚙️  Processing with {max_workers} workers...\n")

        # Process channels in parallel
        processed_channels = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_channel = {
                executor.submit(self.process_channel, channel, csrf_token): channel 
                for channel in channels
            }
            
            # Process completed tasks
            completed = 0
            for future in as_completed(future_to_channel):
                completed += 1
                channel = future_to_channel[future]
                try:
                    result = future.result(timeout=30)
                    if result:
                        processed_channels.append(result)
                        status = "✅"
                    else:
                        status = "❌"
                    
                    # Progress display
                    progress = (completed / self.stats['total']) * 100
                    print(f"[{completed}/{self.stats['total']}] {progress:5.1f}% {status} {channel['title']}")
                    
                except Exception as e:
                    print(f"[{completed}/{self.stats['total']}] ❌ {channel['title']}: Timeout/Error")
                    self.stats['failed'] += 1

        # Sort channels by display number
        processed_channels.sort(
            key=lambda x: int(x['display_number']) 
            if x['display_number'] and 100 <= int(x['display_number']) <= 9999 
            else 9999
        )

        # Write M3U file
        print(f"\n📝 Writing {len(processed_channels)} channels to {output_file}...")
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                # Header
                f.write('#EXTM3U url-tvg="https://github.com/matthuisman/i.mjh.nz/raw/master/Roku/all.xml"\n')
                f.write(f'# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
                f.write(f'# Total channels: {len(processed_channels)}\n\n')
                
                for channel in processed_channels:
                    try:
                        # Channel info line
                        f.write(
                            f'#EXTINF:-1 '
                            f'channel-id="{channel["id"]}" '
                            f'tvg-id="{channel["id"]}" '
                            f'tvg-chno="{channel["display_number"]}" '
                            f'tvg-name="" '
                            f'tvg-logo="" '
                            f'group-title="",{channel["title"]}\n'
                        )
                        
                        # Add KODIPROP for DASH with Widevine
                        if channel['video_type'] == 'DASH' and channel.get('license_server'):
                            f.write('#KODIPROP:inputstreamaddon=inputstream.adaptive\n')
                            f.write('#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha\n')
                            license_key = f'{channel["license_server"]}|Content-Type=application/octet-stream|R{{SSM}}|'
                            f.write(f'#KODIPROP:inputstream.adaptive.license_key={license_key}\n')
                        
                        # Stream URL
                        f.write(f'{channel["stream_url"]}\n\n')
                        
                    except Exception as e:
                        print(f"❌ Error writing channel {channel.get('title', 'Unknown')}: {e}")
                        continue
            
            print(f"✅ M3U playlist saved to {output_file}")
            
        except Exception as e:
            print(f"❌ Error writing file: {e}")
            return

        # Print statistics
        elapsed_time = time.time() - start_time
        print("\n" + "="*60)
        print("📊 STATISTICS")
        print("="*60)
        print(f"Total channels found:  {self.stats['total']}")
        print(f"Successfully processed: {self.stats['success']}")
        print(f"Failed:                {self.stats['failed']}")
        print(f"Success rate:          {(self.stats['success']/self.stats['total']*100):.1f}%")
        print(f"Time elapsed:          {elapsed_time:.2f} seconds")
        print(f"Output file:           {output_file}")
        print("="*60 + "\n")


def main():
    """Main entry point"""
    try:
        # Create extractor instance
        extractor = RokuChannelExtractor()
        
        # Generate M3U playlist
        # Adjust max_workers based on your internet speed:
        # - Fast internet: 10-15 workers
        # - Medium internet: 5-8 workers
        # - Slow internet: 3-5 workers
        extractor.generate_m3u(
            output_file="roku.m3u",
            max_workers=15  # Adjust this value
        )
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()