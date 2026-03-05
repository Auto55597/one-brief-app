import os
import json
import re
import requests
import firebase_admin
import google.generativeai as genai
from firebase_admin import credentials, firestore
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

# --- 1. การเชื่อมต่อ ---
GEMINI_KEY = os.environ.get('GEMINI_API_KEY') or "AIzaSyBaY_QEe3oocCVHQhYlok40RGBa3D9uHrE"

if os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
    cert_dict = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    cred = credentials.Certificate(cert_dict)
else:
    cred = credentials.Certificate("serviceAccountKey.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. AI สรุปข่าวแบบ "Short & Punchy" (เน้นกระชับเพื่อ User) ---
def ai_summarize(title, raw_description):
    try:
        clean_text = re.sub('<.*?>', '', raw_description)[:500]
        # สั่ง AI ให้สรุปสั้นเป็นพิเศษ ไม่เกิน 15-20 คำ
        prompt = f"Summarize this news in ONE very short, punchy sentence (max 15 words). Focus on 'What happened'. Title: {title}. Content: {clean_text}"
        response = model.generate_content(prompt)
        summary = response.text.strip()
        return summary if len(summary) > 10 else f"Quick update on: {title}"
    except:
        return title[:100] + "..."

# --- 3. ล้างข่าวเก่า ---
def delete_old_news():
    threshold = datetime.now(timezone.utc) - timedelta(hours=48)
    old_docs = db.collection("news").where("timestamp", "<", threshold).get()
    for doc in old_docs:
        doc.reference.delete()

# --- 4. แหล่งข่าว ---
CATEGORIES_CONFIG = {
    "Business": "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "Tech": "https://www.theverge.com/rss/index.xml",
    "World News": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Sports": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en"
}

# --- 5. ค้นหารูปภาพ (แบบเข้มข้น) ---
def get_best_image(item, category):
    image_url = ""
    # เช็กทุก Tag ที่น่าจะมีรูป
    tags = [item.find('media:content'), item.find('media:thumbnail'), item.find('enclosure')]
    for tag in tags:
        if tag and tag.get('url'):
            image_url = tag.get('url')
            break
            
    if not image_url and item.description:
        img_match = re.search(r'<img [^>]*src=["\']([^"\']+)["\']', item.description.text)
        if img_match: image_url = img_match.group(1)

    if image_url and image_url.startswith('//'): image_url = 'https:' + image_url
    
    # ถ้าไม่มีรูปจริงๆ ให้ใช้รูปจาก Unsplash ที่ดูเหมือนข่าวจริงที่สุด (High Quality)
    if not image_url or "doubleclick" in image_url or "pixel" in image_url:
        kw = {"Business": "office,finance", "Tech": "gadget,digital", "World News": "news,city", "Sports": "stadium"}
        query = kw.get(category, "news")
        image_url = f"https://images.unsplash.com/photo-1504711434969-e33886168f5c?auto=format&fit=crop&w=800&q=80&sig={category}"
        
    return image_url

# --- 6. รันระบบ ---
def fetch_and_upload():
    delete_old_news()
    for category, url in CATEGORIES_CONFIG.items():
        try:
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.content, features="xml")
            items = soup.find_all('item', limit=10)

            for item in items:
                title = item.title.text.strip()
                doc_id = re.sub(r'[^a-zA-Z0-9]', '', title)[:60]
                doc_ref = db.collection("news").document(doc_id)

                if not doc_ref.get().exists:
                    summary = ai_summarize(title, item.description.text if item.description else "")
                    img = get_best_image(item, category)
                    
                    doc_ref.set({
                        "title": title,
                        "summary": summary,
                        "source": url.split('/')[2].replace('www.', ''),
                        "category": category,
                        "link": item.link.text.strip() if item.link else "",
                        "timestamp": datetime.now(timezone.utc),
                        "image_url": img
                    })
                    print(f"✅ Added: {title[:30]}")
        except Exception as e:
            print(f"❌ Error {category}: {e}")

if __name__ == "__main__":
    fetch_and_upload()