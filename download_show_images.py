import os
import json
import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from io import BytesIO
from PIL import Image, ImageOps

BASE_UPLOAD_URL = "https://programaciontv.com.mx/wp-content/uploads/downloaded-images"
FALLBACK_REPLACEMENT = "https://programaciontv.com.mx/wp-content/uploads/2026/01/pexels-caleboquendo-8254900.webp"
MAX_THREADS = 15
TIMEOUT = 20
ROOT_DIR = os.getcwd()
SCHEDULE_DIR = os.path.join(ROOT_DIR, "schedule")
DOWNLOAD_DIR = os.path.join(ROOT_DIR, "downloaded-images")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def slugify(text):
    """Converts 'Peppa Pig' to 'peppa-pig'"""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    return re.sub(r'[\s_-]+', '-', text)

def download_and_convert(task):
    url, save_path = task
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        r.raise_for_status()
        
        # Open image and strip metadata by creating a fresh copy
        with Image.open(BytesIO(r.content)) as img:
            # Clean metadata and convert to RGB
            image = Image.new("RGB", img.size)
            image.paste(img)

            # Step 3: Crop/Resize to 300x203
            # ImageOps.fit crops to the exact aspect ratio without stretching
            image = ImageOps.fit(image, (300, 203), Image.Resampling.LANCZOS)
            
            # Compress to keep under 10 KB
            max_size_bytes = 10 * 1024
            quality = 85
            
            while quality >= 20:
                buffer = BytesIO()
                image.save(buffer, "WEBP", quality=quality, method=6)
                if buffer.tell() <= max_size_bytes:
                    break
                quality -= 10
            
            with open(save_path, "wb") as f:
                f.write(buffer.getvalue())
                
        return True, url
    except Exception as e:
        print(f"Error processing {url}: {e}")
        return False, url

def process_json(json_path, day):
    channel_slug = os.path.splitext(os.path.basename(json_path))[0]
    output_dir = os.path.join(DOWNLOAD_DIR, channel_slug, day)
    os.makedirs(output_dir, exist_ok=True)
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    download_tasks = []
    
    for show in data.get("schedule", []):
        logo_url = show.get("show_logo", "").strip()
        show_name = show.get("show_name", "default")
        
        if not logo_url:
            continue
        
        # Step 2: Fallback Check
        if "fallback" in logo_url.lower():
            show["show_logo"] = FALLBACK_REPLACEMENT
            continue

        # Step 1: Filename based on show_name
        filename = f"{slugify(show_name)}.webp"
        local_path = os.path.join(output_dir, filename)
        
        # Replace the URL in JSON
        show["show_logo"] = f"{BASE_UPLOAD_URL}/{channel_slug}/{day}/{filename}"
        
        if not os.path.exists(local_path):
            download_tasks.append((logo_url, local_path))
    
    if download_tasks:
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = [executor.submit(download_and_convert, t) for t in download_tasks]
            for _ in as_completed(futures):
                pass
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    for day in ["today", "tomorrow"]:
        day_dir = os.path.join(SCHEDULE_DIR, day)
        if not os.path.isdir(day_dir):
            continue
        for file in os.listdir(day_dir):
            if file.endswith(".json"):
                process_json(os.path.join(day_dir, file), day)

if __name__ == "__main__":
    main()
