import firebase_admin
from firebase_admin import credentials, firestore
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re

import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# --- ส่วนที่แก้ไขเพื่อความปลอดภัยระดับ Global ---
# เช็คว่าถ้ารันบน GitHub ให้ดึงค่าจาก Environment Variable
if os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
    cert_dict = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    cred = credentials.Certificate(cert_dict)
else:
    # ถ้ารันในเครื่องตัวเอง ให้ใช้ไฟล์ JSON ปกติ
    cred = credentials.Certificate("one-brief-app-firebase-adminsdk-fbsvc-7ec5c36c40.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()
# ------------------------------------------

# --- ส่วนที่แก้ไขเพื่อความปลอดภัยระดับ Global ---
# เช็คว่าถ้ารันบน GitHub ให้ดึงค่าจาก Environment Variable
if os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
    cert_dict = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    cred = credentials.Certificate(cert_dict)
else:
    # ถ้ารันในเครื่องตัวเอง ให้ใช้ไฟล์ JSON ปกติ
    cred = credentials.Certificate("one-brief-app-firebase-adminsdk-fbsvc-7ec5c36c40.json")

# 1. เชื่อ connect Firebase
cred = credentials.Certificate("one-brief-app-firebase-adminsdk-fbsvc-7ec5c36c40.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext[:250] + "..." # ขยายความยาวสรุปให้ดูพรีเมียมขึ้น

# 2. จัดกลุ่มสื่อตาม Persona ที่คุณกำหนด (หมวดละ 3 สื่อชั้นนำ)
CATEGORIES_CONFIG = {
    "Business": [ # สำหรับ The Decision Makers (Focus: Strategy, Economy)
        "https://www.cnbc.com/id/10001147/device/rss/rss.html", # CNBC Top News
        "https://www.reutersagency.com/feed/?best-topics=business&post_type=best", # Reuters Business
        "https://www.theguardian.com/business/rss" # The Guardian Business
    ],
    "World News": [ # สำหรับ Modern Investors (Focus: Market Sentiment, Global Events)
        "https://www.aljazeera.com/xml/rss/all.xml", # Global Perspective
        "https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/section/world/rss.xml", # NYT World
        "http://feeds.bbci.co.uk/news/world/rss.xml" # BBC World News
    ],
    "Tech": [ # สำหรับ Tech-Savvy Professionals (Focus: Trends, Innovation)
        "https://techcrunch.com/feed/", # Tech Startups
        "https://www.theverge.com/rss/index.xml", # Consumer Tech & Culture
        "https://wired.com/feed/rss" # Deep Tech & Future Trends
    ]
}

def fetch_and_upload():
    for category, urls in CATEGORIES_CONFIG.items():
        print(f"\n🚀 Processing Category: {category}")
        
        for url in urls:
            try:
                print(f"📡 Fetching from: {url}")
                response = requests.get(url, timeout=15)
                soup = BeautifulSoup(response.content, features="xml")
                items = soup.find_all('item', limit=4) # ดึงจากแต่ละแหล่งมา 4 ข่าว รวมหมวดละ 12 ข่าว

                for item in items:
                    title = item.title.text.strip()
                    link = item.link.text.strip()
                    
                    # พยายามดึงภาพ (Fall-back เป็นรูปสุ่มคุณภาพสูงจาก Unsplash ตามหมวดหมู่)
                    image_url = f"https://images.unsplash.com/photo-1504711434969-e33886168f5c?q=80&w=800&auto=format&fit=crop" # Default
                    if category == "Business":
                        image_url = "https://images.unsplash.com/photo-1460925895917-afdab827c52f?q=80&w=800"
                    elif category == "Tech":
                        image_url = "https://images.unsplash.com/photo-1518770660439-4636190af475?q=80&w=800"

                    data = {
                        "title": title,
                        "summary": clean_html(item.description.text) if item.description else f"Essential briefing for {category} professionals.",
                        "source": url.split('/')[2].replace('www.', ''), # สกัดชื่อโดเมนมาเป็นแหล่งข่าว
                        "category": category,
                        "image_url": image_url,
                        "link": link,
                        "timestamp": datetime.now(timezone.utc),
                    }

                    # ป้องกันข่าวซ้ำ
                    docs = db.collection("news").where("title", "==", title).get()
                    if len(docs) == 0:
                        db.collection("news").add(data)
                        print(f"   ✅ Added: {title[:50]}...")
                    else:
                        print(f"   ⏩ Skipped existing news")

            except Exception as e:
                print(f"   ❌ Error fetching {url}: {e}")

if __name__ == "__main__":
    fetch_and_upload()
    print("\n✨ All high-value news categories updated!")