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
GEMINI_KEY = os.environ.get('GEMINI_API_KEY') or "AIzaSyBaY_QEe3oocCVHQhYlok40RGBa3D9uHrE"

if os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
    # สำหรับรันบน GitHub Actions
    cert_dict = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    cred = credentials.Certificate(cert_dict)
else:
    # สำหรับรันในเครื่องคอมพิวเตอร์ (D:)
    # ตรวจสอบว่าไฟล์ชื่อ serviceAccountKey.json อยู่ในโฟลเดอร์เดียวกับไฟล์นี้
    cred = credentials.Certificate("serviceAccountKey.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. ฟังก์ชัน AI สรุปข่าว ---
def ai_summarize(title, raw_description):
    try:
        prompt = f"Summarize this news into 1-2 concise, professional sentences for a business briefing. Title: {title}. Content: {raw_description}"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ AI Summary failed: {e}")
        return re.sub('<.*?>', '', raw_description)[:200] + "..."

# --- 3. ฟังก์ชันลบข่าวเก่า (เกิน 48 ชม.) ---
def delete_old_news():
    print("🧹 Cleaning up news older than 48 hours...")
    threshold = datetime.now(timezone.utc) - timedelta(hours=48)
    old_docs = db.collection("news").where("timestamp", "<", threshold).get()
    for doc in old_docs:
        doc.reference.delete()
    print(f"🗑️ Cleanup complete.")

# --- 4. แหล่งข่าว (RSS Feeds) ---
CATEGORIES_CONFIG = {
    "Business": "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "Tech": "https://www.theverge.com/rss/index.xml",
    "World News": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Sports": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en"
}

# --- 5. ฟังก์ชันดึงภาพที่ชัดที่สุด ---
def get_best_image(item, category, title):
    image_url = ""
    # 1. ลองดึงจาก Media Tags (BBC, CNBC)
    media = item.find('media:content') or item.find('media:thumbnail') or item.find('enclosure')
    if media and media.get('url'):
        image_url = media.get('url')
    
    # 2. ลองดึงจาก Summary (Google News)
    if not image_url and item.description:
        img_match = re.search(r'<img [^>]*src="([^"]+)"', item.description.text)
        if img_match: 
            image_url = img_match.group(1)
            if image_url.startswith('//'): image_url = 'https:' + image_url

    # 3. ถ้าไม่เจอ ใช้ Unsplash HD แบบระบุ Keyword
    if not image_url or "doubleclick" in image_url:
        safe_sig = re.sub(r'\W+', '', title[:15]) 
        keywords = {"Business": "business", "Tech": "technology", "World News": "world", "Sports": "sports"}
        query = keywords.get(category, "news")
        image_url = f"https://images.unsplash.com/photo-1504711434969-e33886168f5c?auto=format&fit=crop&w=1080&q=80" 
        
    return image_url

# --- 6. กระบวนการหลัก ---
def fetch_and_upload():
    delete_old_news()
    for category, url in CATEGORIES_CONFIG.items():
        print(f"\n🚀 Fetching: {category}")
        try:
            response = requests.get(url, timeout=15)
            soup = BeautifulSoup(response.content, features="xml")
            items = soup.find_all('item', limit=8)

            for item in items:
                title = item.title.text.strip()
                # ป้องกันข่าวซ้ำโดยใช้ชื่อข่าวเป็น ID
                doc_id = re.sub(r'[^a-zA-Z0-9]', '', title)[:60]
                doc_ref = db.collection("news").document(doc_id)

                if not doc_ref.get().exists:
                    raw_desc = item.description.text if item.description else ""
                    summary = ai_summarize(title, raw_desc)
                    final_image_url = get_best_image(item, category, title)
                    
                    doc_ref.set({
                        "title": title,
                        "summary": summary,
                        "source": url.split('/')[2].replace('www.', ''),
                        "category": category,
                        "link": item.link.text.strip() if item.link else "",
                        "timestamp": datetime.now(timezone.utc),
                        "image_url": final_image_url
                    })
                    print(f"✅ Added: {title[:40]}...")
        except Exception as e:
            print(f"❌ Error in {category}: {e}")

if __name__ == "__main__":
    fetch_and_upload()
    print("\n✨ Done!")