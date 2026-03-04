import os
import json
import re
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# --- 1. ตั้งค่าการเชื่อมต่อ Firebase (Smart Connection) ---
# ระบบจะเช็คเองว่ารันที่ไหน เพื่อความปลอดภัยระดับสากล
if os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
    # กรณีรันบน GitHub Actions (ดึงค่าจาก Secrets)
    cert_dict = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    cred = credentials.Certificate(cert_dict)
else:
    # กรณีรันในเครื่องตัวเอง (ใช้ไฟล์ JSON ปกติ)
    # ตรวจสอบชื่อไฟล์ให้ตรงกับที่คุณมีในเครื่องนะครับ
    cred = credentials.Certificate("one-brief-app-firebase-adminsdk-fbsvc-7ec5c36c40.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 2. ฟังก์ชันช่วยจัดการข้อมูล ---
def clean_html(raw_html):
    """ลบ Tag HTML และจำกัดความยาวคำโปรย"""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext[:250] + "..." 

# --- 3. แหล่งข่าวระดับโลก (RSS Feeds) ---
CATEGORIES_CONFIG = {
    "Business": [ 
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "https://www.reutersagency.com/feed/?best-topics=business&post_type=best",
        "https://www.theguardian.com/business/rss"
    ],
    "World News": [ 
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/section/world/rss.xml",
        "http://feeds.bbci.co.uk/news/world/rss.xml"
    ],
    "Tech": [ 
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://wired.com/feed/rss"
    ]
}

# --- 4. ฟังก์ชันหลักในการดึงข่าวและอัปโหลด ---
def fetch_and_upload():
    for category, urls in CATEGORIES_CONFIG.items():
        print(f"\n🚀 Processing Category: {category}")
        
        for url in urls:
            try:
                print(f"📡 Fetching from: {url}")
                response = requests.get(url, timeout=15)
                soup = BeautifulSoup(response.content, features="xml")
                items = soup.find_all('item', limit=4) 

                for item in items:
                    title = item.title.text.strip()
                    link = item.link.text.strip()
                    
                    # เลือกรูปภาพสุ่มตามหมวดหมู่ (เพื่อให้แอปดูสวยงาม)
                    image_url = "https://images.unsplash.com/photo-1504711434969-e33886168f5c?q=80&w=800" # General
                    if category == "Business":
                        image_url = "https://images.unsplash.com/photo-1460925895917-afdab827c52f?q=80&w=800"
                    elif category == "Tech":
                        image_url = "https://images.unsplash.com/photo-1518770660439-4636190af475?q=80&w=800"

                    data = {
                        "title": title,
                        "summary": clean_html(item.description.text) if item.description else f"Essential briefing for {category} professionals.",
                        "source": url.split('/')[2].replace('www.', ''),
                        "category": category,
                        "image_url": image_url,
                        "link": link,
                        "timestamp": datetime.now(timezone.utc), # ใช้เวลาสากล
                    }

                    # ป้องกันข่าวซ้ำ (Check by Title)
                    docs = db.collection("news").where("title", "==", title).limit(1).get()
                    if len(docs) == 0:
                        db.collection("news").add(data)
                        print(f"   ✅ Added: {title[:50]}...")
                    else:
                        print(f"   ⏩ Skipped: Already exists")

            except Exception as e:
                print(f"   ❌ Error fetching {url}: {e}")

# --- 5. สั่งเริ่มทำงาน ---
if __name__ == "__main__":
    fetch_and_upload()
    print("\n✨ All global news categories updated successfully!")