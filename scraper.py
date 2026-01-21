import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import pytz
import os
from pathlib import Path
import time
import re

# Configuration
LINEUP_ID = "3129"  # StarTV Mexico
BASE_URL = "https://www.reportv.com.ar/finder/channel"
FILTER_FILE = "filter.txt"
MEXICO_TZ = pytz.timezone('America/Mexico_City')

def read_channel_ids():
    """Read channel IDs from filter.txt file"""
    try:
        with open(FILTER_FILE, 'r') as f:
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

def fetch_schedule(channel_id, date, start_hour):
    """Fetch schedule for a specific channel, date and time"""
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
        print(f"Error fetching schedule: {e}")
        return None

def parse_datetime(datetime_text):
    """
    Parse datetime from format '21-01 01:51hs.' or '21/01 01:51hs.'
    Returns (day, month, hour, minute) tuple
    """
    try:
        # Match both formats: 21-01 or 21/01
        match = re.search(r'(\d{2})[-/](\d{2})\s+(\d{2}):(\d{2})', datetime_text)
        if not match:
            return None
        
        day = match.group(1)
        month = match.group(2)
        hour = match.group(3)
        minute = match.group(4)
        
        return day, month, hour, minute
    except Exception as e:
        print(f"Error parsing datetime '{datetime_text}': {e}")
        return None

def parse_programs_from_html(html_content, target_date):
    """Parse programs from HTML response"""
    if not html_content:
        return None, []
    
    soup = BeautifulSoup(html_content, 'html.parser')
    programs = []
    channel_name = "Unknown"
    
    # Try to find channel name
    channel_elem = soup.find('span', class_='nombre_senial')
    if channel_elem:
        channel_name = channel_elem.get_text(strip=True)
    
    # Find all program containers
    program_divs = soup.find_all('div', class_='channel-programa')
    
    target_date_obj = datetime.strptime(target_date, '%Y-%m-%d')
    
    for div in program_divs:
        try:
            # Get program image
            img = div.find('img', class_='lazyload')
            show_logo = img.get('data-src', '') if img else ''
            if show_logo and not show_logo.startswith('http'):
                show_logo = f"https://www.reportv.com.ar{show_logo}"
            
            # Get program title
            title_span = div.find('span')
            show_name = title_span.get_text(strip=True) if title_span else ''
            
            # Get datetime
            datetime_span = div.find('span', class_='grid_fecha_hora')
            datetime_text = datetime_span.get_text(strip=True) if datetime_span else ''
            
            # Parse datetime
            parsed = parse_datetime(datetime_text)
            if not parsed:
                continue
            
            day, month, hour, minute = parsed
            
            # Verify this program is on our target date
            program_date = datetime(target_date_obj.year, int(month), int(day))
            if program_date.date() != target_date_obj.date():
                continue
            
            start_time = f"{hour}:{minute}"
            
            # Get category from class
            category_classes = div.get('class', [])
            show_category = ''
            for cls in category_classes:
                if cls.startswith('Categoria '):
                    show_category = cls.replace('Categoria ', '')
                    break
            
            if show_name:
                programs.append({
                    "show_name": show_name,
                    "show_logo": show_logo,
                    "show_category": show_category,
                    "start_time": start_time,
                    "end_time": "",
                    "episode_description": ""
                })
                
        except Exception as e:
            print(f"Error parsing program: {e}")
            continue
    
    return channel_name, programs

def fetch_full_day_schedule(channel_id, date):
    """Fetch complete 24-hour schedule by making multiple requests"""
    print(f"    Fetching full day schedule for {date}...")
    
    all_programs = {}
    channel_name = "Unknown"
    
    # Make requests every 3 hours to cover the full day
    time_slots = ["00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00"]
    
    for idx, time_slot in enumerate(time_slots):
        print(f"      → Request {idx+1}/{len(time_slots)}: {time_slot}", end='')
        
        html = fetch_schedule(channel_id, date, time_slot)
        if html:
            name, programs = parse_programs_from_html(html, date)
            if name != "Unknown":
                channel_name = name
            
            # Add programs to dictionary (using start_time as key to avoid duplicates)
            for program in programs:
                key = program['start_time']
                if key not in all_programs:
                    all_programs[key] = program
                    
            print(f" - Found {len(programs)} programs")
        else:
            print(" - Failed")
        
        # Small delay between requests
        if idx < len(time_slots) - 1:
            time.sleep(0.5)
    
    # Convert dict to sorted list
    sorted_programs = sorted(all_programs.values(), key=lambda x: x['start_time'])
    
    # Calculate end times
    for i in range(len(sorted_programs)):
        if i < len(sorted_programs) - 1:
            sorted_programs[i]["end_time"] = sorted_programs[i + 1]["start_time"]
        else:
            sorted_programs[i]["end_time"] = "23:59"
    
    print(f"    Total unique programs collected: {len(sorted_programs)}")
    return channel_name, sorted_programs

def save_schedule(channel_name, date, programs, folder):
    """Save schedule to JSON file"""
    folder_path = Path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)
    
    date_obj = datetime.strptime(date, '%Y-%m-%d')
    formatted_date = date_obj.strftime('%d/%m/%Y')
    
    # Sanitize filename
    filename = channel_name.lower().replace(' ', '_').replace('/', '_').replace('\\', '_')
    filename = re.sub(r'[^\w\s-]', '', filename).strip() + '.json'
    filepath = folder_path / filename
    
    output = {
        "channel": channel_name,
        "date": formatted_date,
        "schedule": programs
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Saved {len(programs)} programs for {channel_name} to {filepath}")

def main():
    """Main function to orchestrate the scraping process"""
    print("=" * 60)
    print("TV Schedule Scraper for StarTV Mexico")
    print("=" * 60)
    
    channel_ids = read_channel_ids()
    if not channel_ids:
        print("No channel IDs found in filter.txt")
        return
    
    print(f"Found {len(channel_ids)} channel(s) to process")
    
    today, tomorrow = get_mexican_dates()
    print(f"Today (Mexico): {today}")
    print(f"Tomorrow (Mexico): {tomorrow}")
    print("-" * 60)
    
    for idx, channel_id in enumerate(channel_ids, 1):
        print(f"\n[{idx}/{len(channel_ids)}] Processing Channel ID: {channel_id}")
        
        # Fetch today's schedule
        print(f"  📅 TODAY ({today}):")
        channel_name, programs_today = fetch_full_day_schedule(channel_id, today)
        if programs_today:
            save_schedule(channel_name, today, programs_today, "schedule/today")
        else:
            print(f"  ⚠ No programs found for today")
        
        time.sleep(1)
        
        # Fetch tomorrow's schedule
        print(f"\n  📅 TOMORROW ({tomorrow}):")
        channel_name, programs_tomorrow = fetch_full_day_schedule(channel_id, tomorrow)
        if programs_tomorrow:
            save_schedule(channel_name, tomorrow, programs_tomorrow, "schedule/tomorrow")
        else:
            print(f"  ⚠ No programs found for tomorrow")
        
        print()
        time.sleep(1)
    
    print("=" * 60)
    print("✅ Schedule scraping completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
