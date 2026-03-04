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
    cert_dict = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    cred = credentials.Certificate(cert_dict)
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY') or GEMINI_KEY)
else:
    cred = credentials.Certificate("one-brief-app-firebase-adminsdk-fbsvc-7ec5c36c40.json")
    genai.configure(api_key=GEMINI_KEY)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. ฟังก์ชัน AI สรุปข่าว ---
def ai_summarize(title, raw_description):
    try:
        prompt = f"Summarize this news into 1-2 concise, professional sentences for a business briefing. Title: {title}. Content: {raw_description}"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ AI Summary failed: {e}")
        cleanr = re.compile('<.*?>')
        text = re.sub(cleanr, '', raw_description)
        return text[:200] + "..."

# --- 3. ฟังก์ชันลบข่าวเก่า ---
def delete_old_news():
    print("🧹 Cleaning up news older than 48 hours...")
    threshold = datetime.now(timezone.utc) - timedelta(hours=48)
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

# --- 5. ฟังก์ชันดึงภาพ (เน้นความคมชัดและความไม่ซ้ำ) ---
def get_image_from_item(item, category, title):
    image_url = None
    
    # 1. ลองหาจาก <media:content> หรือ <media:thumbnail>
    media = item.find('media:content') or item.find('media:thumbnail') or item.find('content')
    if media and media.get('url'):
        image_url = media.get('url')
    
    # 2. ถ้าไม่เจอ ลองหาจาก <enclosure>
    if not image_url:
        enclosure = item.find('enclosure')
        if enclosure and enclosure.get('url'):
            image_url = enclosure.get('url')
            
    # 3. กรณีไม่เจอภาพจริง ให้ใช้ Unsplash แบบระบุความละเอียด (1080x720) และ Signature ไม่ให้ซ้ำ
    if not image_url:
        # สร้าง ID สุ่มจากชื่อข่าว (เอาเฉพาะตัวอักษร 15 ตัวแรก)
        safe_sig = re.sub(r'\W+', '', title[:15]) 
        keywords = {
            "Business": "business,finance,trading",
            "Tech": "technology,coding,digital",
            "World News": "world,map,city"
        }
        query = keywords.get(category, "news")
        
        # เพิ่มขนาด 1080x720 เพื่อความคมชัด และพ่วง &sig เพื่อให้แต่ละข่าวได้ภาพต่างกัน
        image_url = f"https://source.unsplash.com/featured/1080x720?{query}&sig={safe_sig}"
        
    return image_url

# --- 6. กระบวนการหลัก ---
def fetch_and_upload():
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
                        summary = ai_summarize(title, raw_desc)
                        
                        # ดึงภาพ (ส่ง title ไปด้วยเพื่อสุ่มภาพไม่ซ้ำ)
                        final_image_url = get_image_from_item(item, category, title)
                        
                        data = {
                            "title": title,
                            "summary": summary,
                            "source": url.split('/')[2].replace('www.', ''),
                            "category": category,
                            "link": item.link.text.strip(),
                            "timestamp": datetime.now(timezone.utc),
                            "image_url": final_image_url
                        }
                        db.collection("news").add(data)
                        
                        source_type = "Real" if "unsplash" not in final_image_url else "Random HD"
                        print(f"✅ Added: {title[:50]}... ({source_type})")
                    else:
                        print(f"⏩ Skipped: {title[:30]} (Duplicate)")
            except Exception as e:
                print(f"❌ Error fetching {url}: {e}")

if __name__ == "__main__":
    fetch_and_upload()
    print("\n✨ Process Complete!")