import os
import json
import re
import requests
import firebase_admin
import google.generativeai as genai
from firebase_admin import credentials, firestore
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

# --- 1. ตั้งค่าการเชื่อมต่อ (Firebase & Gemini) ---
GEMINI_KEY = "AIzaSyBaY_QEe3oocCVHQhYlok40RGBa3D9uHrE"

if os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
    # กรณีรันบน GitHub Actions
    cert_dict = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    cred = credentials.Certificate(cert_dict)
    # ใช้ Key จาก Secrets ถ้ามี ถ้าไม่มีให้ใช้ตัวแปรข้างบน
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY') or GEMINI_KEY)
else:
    # กรณีรันในเครื่องตัวเอง
    cred = credentials.Certificate("one-brief-app-firebase-adminsdk-fbsvc-7ec5c36c40.json")
    genai.configure(api_key=GEMINI_KEY)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. ฟังก์ชัน AI สรุปข่าว (จุดที่ 2: Professional Summary) ---
def ai_summarize(title, raw_description):
    try:
        # สั่ง AI ให้สรุปเป็นภาษาไทยหรืออังกฤษตามความเหมาะสม (ในที่นี้สั่งเป็นสรุปกระชับ)
        prompt = f"Summarize this news into 1-2 concise, professional sentences for a business briefing. Title: {title}. Content: {raw_description}"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ AI Summary failed: {e}")
        # ถ้า AI พัง ให้ตัดข้อความธรรมดาแทน
        cleanr = re.compile('<.*?>')
        text = re.sub(cleanr, '', raw_description)
        return text[:200] + "..."

# --- 3. ฟังก์ชันลบข่าวเก่า (จุดที่ 1: Data Management) ---
def delete_old_news():
    print("🧹 Cleaning up news older than 48 hours...")
    threshold = datetime.now(timezone.utc) - timedelta(hours=48)
    
    # ดึงข่าวที่เก่ากว่าเวลาที่กำหนด
    old_docs = db.collection("news").where("timestamp", "<", threshold).get()
    
    count = 0
    for doc in old_docs:
        doc.reference.delete()
        count += 1
    print(f"🗑️ Deleted {count} old articles.")

# --- 4. แหล่งข่าว (RSS Feeds) ---
CATEGORIES_CONFIG = {
    "Business": ["https://www.cnbc.com/id/10001147/device/rss/rss.html"],
    "Tech": ["https://techcrunch.com/feed/"],
    "World News": ["http://feeds.bbci.co.uk/news/world/rss.xml"]
}

# --- 5. กระบวนการหลัก ---
def fetch_and_upload():
    # ลบขยะก่อน (จุดที่ 1)
    delete_old_news()
    
    for category, urls in CATEGORIES_CONFIG.items():
        print(f"\n🚀 Category: {category}")
        for url in urls:
            try:
                response = requests.get(url, timeout=15)
                soup = BeautifulSoup(response.content, features="xml")
                items = soup.find_all('item', limit=5)

                for item in items:
                    title = item.title.text.strip()
                    
                    # เช็คข่าวซ้ำ
                    duplicate = db.collection("news").where("title", "==", title).limit(1).get()
                    if len(duplicate) == 0:
                        raw_desc = item.description.text if item.description else ""
                        
                        # ใช้ AI สรุปข่าว (จุดที่ 2)
                        summary = ai_summarize(title, raw_desc)
                        
                        data = {
                            "title": title,
                            "summary": summary,
                            "source": url.split('/')[2].replace('www.', ''),
                            "category": category,
                            "link": item.link.text.strip(),
                            "timestamp": datetime.now(timezone.utc), # บันทึกเวลามาตรฐานสากล (จุดที่ 3)
                            "image_url": "https://images.unsplash.com/photo-1504711434969-e33886168f5c?q=80&w=800"
                        }
                        db.collection("news").add(data)
                        print(f"✅ Added: {title[:50]}...")
                    else:
                        print(f"⏩ Skipped: {title[:30]} (Duplicate)")
            except Exception as e:
                print(f"❌ Error fetching {url}: {e}")

if __name__ == "__main__":
    fetch_and_upload()
    print("\n✨ Process Complete!")