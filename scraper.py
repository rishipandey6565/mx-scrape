import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import pytz
import os
from pathlib import Path
import time

# Configuration
LINEUP_ID = "3129"  # StarTV Mexico
BASE_URL = "https://www.reportv.com.ar/finder/channel"
FILTER_FILE = "filter.txt"
MEXICO_TZ = pytz.timezone('America/Mexico_City')

def read_channel_ids():
    """Read channel IDs from filter.txt file"""
    try:
        with open(FILTER_FILE, 'r') as f:
            # Read lines and strip whitespace, filter empty lines
            channel_ids = [line.strip() for line in f if line.strip()]
        return channel_ids
    except FileNotFoundError:
        print(f"Error: {FILTER_FILE} not found!")
        return []

def get_mexican_dates():
    """Get today and tomorrow dates in Mexico City timezone"""
    now_mexico = datetime.now(MEXICO_TZ)
    today = now_mexico.strftime('%Y-%m-%d')
    tomorrow = (now_mexico + timedelta(days=1)).strftime('%Y-%m-%d')
    return today, tomorrow

def fetch_schedule(channel_id, date, start_hour="00:00"):
    """Fetch schedule for a specific channel and date"""
    payload = {
        "idAlineacion": LINEUP_ID,
        "idSenial": channel_id,
        "fecha": date,
        "hora": start_hour
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.post(BASE_URL, data=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error fetching schedule for channel {channel_id}: {e}")
        return None

def parse_schedule(html_content, date):
    """Parse HTML content and extract schedule information"""
    if not html_content:
        return None
    
    soup = BeautifulSoup(html_content, 'html.parser')
    programs = []
    channel_name = "Unknown"
    
    # Find all program items
    items = soup.find_all('div', class_='item-program')
    
    for item in items:
        try:
            # Extract channel name (only once)
            if channel_name == "Unknown":
                channel_elem = item.find('p', class_='aContinuacionNombreSenial')
                if channel_elem and channel_elem.get('title'):
                    channel_name = channel_elem.get('title').strip()
            
            # Extract show logo
            logo_elem = item.find('img', class_='evento_imagen')
            show_logo = logo_elem.get('src', '') if logo_elem else ''
            
            # Extract show title
            title_elem = item.find('p', class_='evento_titulo texto_a_continuacion dotdotdot')
            show_name = title_elem.get_text(strip=True) if title_elem else ''
            
            # Extract category/genre
            genre_elem = item.find('p', class_='evento_genero')
            show_category = genre_elem.get_text(strip=True) if genre_elem else ''
            
            # Extract date and time
            datetime_elem = item.find('p', class_='fechaHora')
            datetime_text = datetime_elem.get_text(strip=True) if datetime_elem else ''
            
            # Parse datetime (format: "22/01 03:02hs.")
            start_time = ""
            if datetime_text:
                try:
                    time_part = datetime_text.split()[-1].replace('hs.', '').strip()
                    start_time = time_part
                except:
                    pass
            
            if show_name and start_time:
                programs.append({
                    "show_name": show_name,
                    "show_logo": show_logo,
                    "show_category": show_category,
                    "start_time": start_time,
                    "end_time": "",  # Will be calculated
                    "episode_description": ""  # Not available in list view
                })
        except Exception as e:
            print(f"Error parsing program item: {e}")
            continue
    
    # Calculate end times
    for i in range(len(programs)):
        if i < len(programs) - 1:
            programs[i]["end_time"] = programs[i + 1]["start_time"]
        else:
            programs[i]["end_time"] = "23:59"
    
    return channel_name, programs

def save_schedule(channel_name, date, programs, folder):
    """Save schedule to JSON file"""
    # Create folder structure
    folder_path = Path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)
    
    # Format date for display
    date_obj = datetime.strptime(date, '%Y-%m-%d')
    formatted_date = date_obj.strftime('%d/%m/%Y')
    
    # Create filename from channel name (sanitize)
    filename = channel_name.lower().replace(' ', '_').replace('/', '_') + '.json'
    filepath = folder_path / filename
    
    # Prepare output data
    output = {
        "channel": channel_name,
        "date": formatted_date,
        "schedule": programs
    }
    
    # Save to file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Saved {len(programs)} programs for {channel_name} to {filepath}")

def main():
    """Main function to orchestrate the scraping process"""
    print("=" * 60)
    print("TV Schedule Scraper for StarTV Mexico")
    print("=" * 60)
    
    # Read channel IDs
    channel_ids = read_channel_ids()
    if not channel_ids:
        print("No channel IDs found in filter.txt")
        return
    
    print(f"Found {len(channel_ids)} channel(s) to process")
    
    # Get dates in Mexico timezone
    today, tomorrow = get_mexican_dates()
    print(f"Today (Mexico): {today}")
    print(f"Tomorrow (Mexico): {tomorrow}")
    print("-" * 60)
    
    # Process each channel
    for idx, channel_id in enumerate(channel_ids, 1):
        print(f"\n[{idx}/{len(channel_ids)}] Processing Channel ID: {channel_id}")
        
        # Fetch and save today's schedule
        print(f"  → Fetching today's schedule...")
        html_today = fetch_schedule(channel_id, today)
        if html_today:
            channel_name, programs_today = parse_schedule(html_today, today)
            if programs_today:
                save_schedule(channel_name, today, programs_today, "schedule/today")
        
        time.sleep(1)  # Be nice to the server
        
        # Fetch and save tomorrow's schedule
        print(f"  → Fetching tomorrow's schedule...")
        html_tomorrow = fetch_schedule(channel_id, tomorrow)
        if html_tomorrow:
            channel_name, programs_tomorrow = parse_schedule(html_tomorrow, tomorrow)
            if programs_tomorrow:
                save_schedule(channel_name, tomorrow, programs_tomorrow, "schedule/tomorrow")
        
        time.sleep(1)  # Be nice to the server
    
    print("\n" + "=" * 60)
    print("Schedule scraping completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
