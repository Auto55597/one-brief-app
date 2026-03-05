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
    cred = credentials.Certificate("serviceAccountKey.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. ฟังก์ชัน AI สรุปข่าว ---
def ai_summarize(title, raw_description):
    try:
        # ทำความสะอาด tag html ก่อนส่งให้ AI
        clean_text = re.sub('<.*?>', '', raw_description)
        prompt = f"Summarize this news into 1-2 concise, professional sentences for a business briefing. Title: {title}. Content: {clean_text}"
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

# --- 5. ฟังก์ชันดึงภาพที่ชัดที่สุด (V.2 ปรับปรุงใหม่) ---
def get_best_image(item, category, title):
    image_url = ""
    
    # 1. ลองดึงจาก Media Tags แบบครอบคลุม (BBC, CNBC, Verge)
    media_tags = [
        item.find('media:content'), 
        item.find('media:thumbnail'), 
        item.find('enclosure'),
        item.find('image')
    ]
    
    for tag in media_tags:
        if tag and tag.get('url'):
            image_url = tag.get('url')
            break

    # 2. ถ้ายังไม่เจอ ลองดึงจากใน Description (Google News มักแอบไว้ที่นี่)
    if not image_url and item.description:
        img_match = re.search(r'<img [^>]*src=["\']([^"\']+)["\']', item.description.text)
        if img_match: 
            image_url = img_match.group(1)

    # ปรับแต่ง URL (ถ้ามาแค่ // หรือเป็นพิกเซลจิ๋วของโฆษณา)
    if image_url:
        if image_url.startswith('//'): 
            image_url = 'https:' + image_url
        if "doubleclick" in image_url or "pixel" in image_url:
            image_url = ""

    # 3. (Fallback) ถ้าไม่เจอรูปจริงๆ ให้ใช้รูปจาก Unsplash ตามหมวดหมู่เพื่อให้แอปสวยงาม
    if not image_url:
        keywords = {
            "Business": "business,finance",
            "Tech": "technology,gadget",
            "World News": "global,news",
            "Sports": "stadium,sport"
        }
        query = keywords.get(category, "news")
        # ใช้ Unsplash Source แบบระบุคำค้นหา
        image_url = f"https://images.unsplash.com/photo-1504711434969-e33886168f5c?auto=format&fit=crop&w=800&q=80&sig={category}"
        
    return image_url

# --- 6. กระบวนการหลัก ---
def fetch_and_upload():
    delete_old_news()
    for category, url in CATEGORIES_CONFIG.items():
        print(f"\n🚀 Fetching: {category}")
        try:
            response = requests.get(url, timeout=15)
            # ใช้ lxml parser สำหรับความเร็วและแม่นยำ
            soup = BeautifulSoup(response.content, features="xml")
            items = soup.find_all('item', limit=8)

            for item in items:
                title = item.title.text.strip()
                # ทำความสะอาด ID ให้ปลอดภัย
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
                else:
                    print(f"⏩ Skipped: {title[:40]}...")
        except Exception as e:
            print(f"❌ Error in {category}: {e}")

if __name__ == "__main__":
    fetch_and_upload()
    print("\n✨ All tasks completed!")