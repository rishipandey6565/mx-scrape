import os
import gzip
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, time
import pytz
import re

# --- Configuration ---
EPG_URLS = [
    "https://epgshare01.online/epgshare01/epg_ripper_MX1.xml.gz",
]

OUTPUT_DIR_TODAY = "schedule/today"
OUTPUT_DIR_TOMORROW = "schedule/tomorrow"

# Set Target Timezone to Mexico City
TZ_MEXICO = pytz.timezone('America/Mexico_City')

def get_xml_root(url):
    """
    Downloads and parses XML from a URL (handles .gz and raw .xml).
    """
    try:
        print(f"Downloading: {url}")
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        content = response.content
        
        # Check if it is gzipped (Magic number 1f 8b) or URL ends in .gz
        if url.endswith('.gz') or content[:2] == b'\x1f\x8b':
            try:
                content = gzip.decompress(content)
            except OSError:
                print("Warning: Failed to decompress. Trying as plain text.")
        
        return ET.fromstring(content)
    except Exception as e:
        print(f"Error processing {url}: {e}")
        return None

def parse_xmltv_date(date_str):
    """
    Parses XMLTV date format: YYYYMMDDHHMMSS +/-HHMM
    Returns a datetime object in UTC (or timezone aware).
    """
    if not date_str:
        return None
    
    # Remove space before timezone if present for both + and - offsets
    date_str = date_str.replace(" +", "+").replace(" -", "-")
    
    try:
        dt = datetime.strptime(date_str, "%Y%m%d%H%M%S%z")
        return dt
    except ValueError:
        return None

def sanitize_filename(name):
    """Converts 'Sky Serie' to 'Sky-Serie' and removes illegal chars"""
    clean_name = re.sub(r'[^a-zA-Z0-9]', '-', name).strip('-')
    # Collapse multiple hyphens into one
    clean_name = re.sub(r'-+', '-', clean_name)
    return clean_name

def extract_schedule():
    # Prepare data structure: { 'Channel Name': [list of programs] }
    all_extracted_data = {}
    
    # Iterate over all URLs
    for url in EPG_URLS:
        root = get_xml_root(url)
        if root is None:
            continue
            
        print("Parsing XML data...")

        # 1. Map Channel IDs to Display Names from the XML itself
        channel_id_map = {} 
        
        for channel in root.findall('channel'):
            c_id = channel.get('id')
            display_name = channel.find('display-name')
            
            # Use display name if available, otherwise fallback to ID
            c_name = display_name.text if display_name is not None else c_id
            
            # Remove 'Canal ' prefix if present (Case Insensitive)
            if c_name:
                c_name = re.sub(r'^Canal\s+', '', c_name, flags=re.IGNORECASE)
            
            if c_id:
                channel_id_map[c_id] = c_name

        print(f"Found {len(channel_id_map)} channels in XML.")

        # 2. Parse Programmes
        count_progs = 0
        for prog in root.findall('programme'):
            channel_id = prog.get('channel')
            
            # Only process if we know the channel name
            if channel_id in channel_id_map:
                channel_name_clean = channel_id_map[channel_id]
                
                start_raw = parse_xmltv_date(prog.get('start'))
                stop_raw = parse_xmltv_date(prog.get('stop'))
                
                if not start_raw or not stop_raw:
                    continue

                # Convert to Mexico City Time
                start_mx = start_raw.astimezone(TZ_MEXICO)
                stop_mx = stop_raw.astimezone(TZ_MEXICO)
                
                # Extract Metadata
                title_el = prog.find('title')
                desc_el = prog.find('desc')
                cat_el = prog.find('category')
                icon_el = prog.find('icon')
                
                program_data = {
                    "show_name": title_el.text if title_el is not None else "No Title",
                    "description": desc_el.text if desc_el is not None else "",
                    "category": cat_el.text if cat_el is not None else "",
                    "start_dt": start_mx, 
                    "end_dt": stop_mx,
                    "logo_url": icon_el.get('src') if icon_el is not None else ""
                }
                
                if channel_name_clean not in all_extracted_data:
                    all_extracted_data[channel_name_clean] = []
                all_extracted_data[channel_name_clean].append(program_data)
                count_progs += 1
        
        print(f"Extracted {count_progs} programs.")

    # 3. Process and Save Data
    now_mexico = datetime.now(TZ_MEXICO)
    today_date = now_mexico.date()
    tomorrow_date = today_date + timedelta(days=1)
    
    # Create directories
    os.makedirs(OUTPUT_DIR_TODAY, exist_ok=True)
    os.makedirs(OUTPUT_DIR_TOMORROW, exist_ok=True)
    
    print(f"Saving schedules for {today_date} and {tomorrow_date}...")

    files_saved = 0
    for ch_name, programs in all_extracted_data.items():
        # Sort programs by start time
        programs.sort(key=lambda x: x['start_dt'])
        
        for target_date, folder in [(today_date, OUTPUT_DIR_TODAY), (tomorrow_date, OUTPUT_DIR_TOMORROW)]:
            daily_schedule = []
            
            day_start = TZ_MEXICO.localize(datetime.combine(target_date, time.min))
            day_end = TZ_MEXICO.localize(datetime.combine(target_date, time.max))
            
            for p in programs:
                p_start = p['start_dt']
                p_end = p['end_dt']
                
                if p_start <= day_end and p_end >= day_start:
                    display_start = p_start
                    if p_start < day_start:
                        display_start = day_start
                    
                    # CHANGED: Format to HH:MM only
                    fmt_time = "%H:%M"
                    
                    entry = {
                        "show_name": p['show_name'],
                        "show_logo": p['logo_url'],
                        "show_category": p['category'],
                        "start_time": display_start.strftime(fmt_time),
                        "end_time": p_end.strftime(fmt_time),
                        "episode_description": p['description']
                    }
                    daily_schedule.append(entry)
            
            if daily_schedule:
                # CHANGED: Date format to DD/MM/YYYY
                fmt_date = "%d/%m/%Y"
                
                json_output = {
                    "channel": ch_name, # Renamed key
                    "date": target_date.strftime(fmt_date),
                    "schedule": daily_schedule # Renamed key
                }
                
                filename = f"{sanitize_filename(ch_name)}.json"
                file_path = os.path.join(folder, filename)
                
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(json_output, f, indent=2, ensure_ascii=False)
                    files_saved += 1
                except OSError as e:
                    print(f"Error saving file for {ch_name}: {e}")

    print(f"Done! Saved {files_saved} JSON files.")

if __name__ == "__main__":
    extract_schedule()
