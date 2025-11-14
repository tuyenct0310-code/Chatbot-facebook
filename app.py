import os, json, random, requests
from flask import Flask, request, jsonify
from openai import OpenAI
import google.generativeai as genai

app = Flask(__name__)

# ==========================
#  ENV
# ==========================
PAGE_TOKEN   = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
OPENAI_KEY   = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "")

FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# ==========================
#  OpenAI
# ==========================
try:
    client = OpenAI(api_key=OPENAI_KEY)
    print("✅ OpenAI đã sẵn sàng")
except Exception as e:
    print("❌ Lỗi OpenAI:", e)
    client = None

# ==========================
#  Gemini
# ==========================
try:
    genai.configure(api_key=GEMINI_KEY)
    print("✅ Gemini đã sẵn sàng (1.5 Flash)")
except Exception as e:
    print("❌ Lỗi Gemini:", e)

GEMINI_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

GEMINI_GENERATION_CONFIG = {
    "temperature": 0.7,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 200
}

# ==========================
#  LOAD ALL JSON IN /data
# ==========================
def load_all_data(folder="data"):
    db = {}
    if not os.path.exists(folder):
        print("❌ Không tìm thấy thư mục 'data'")
        return db

    for file in os.listdir(folder):
        if file.endswith(".json"):
            try:
                with open(os.path.join(folder, file), "r", encoding="utf8") as f:
                    key = file.replace(".json", "")
                    db[key] = json.load(f)
            except Exception as e:
                print("❌ Lỗi đọc", file, e)

    print("✅ Đã nạp:", list(db.keys()))
    return db

DATABASE = load_all_data()

# ==========================
#  TÌM TRONG JSON (Fast path)
# ==========================
def find_in_json(text):
    if not DATABASE:
        return None

    t = text.lower()

    for file_key, data in DATABASE.items():
        triggers = data.get("chatbot_triggers", [])
        for tr in triggers:
            keywords = tr.get("keywords", [])
            if any(k in t for k in keywords):
                resp = tr.get("response", "")
                if isinstance(resp, list):
                    return random.choice(resp)
                return random.choice(resp.splitlines())
    return None

# ==========================
#  CONTEXT FILTER (RAG mini)
# ==========================
def find_relevant_context(user_text):
    text = user_text.lower()
    result = {}

    for file_key, content in DATABASE.items():
        projects = content.get("highlight_projects", [])
        products = content.get("products", [])
        found = []

        for item in projects:
            if item.get("name", "").lower() in text:
                found.append(item)

        for item in products:
            if item.get("name", "").lower() in text:
                found.append(item)

        if found:
            result[file_key] = {"relevant_items_found": found}

    if not result:
        return json.dumps({"note": "Không tìm thấy sản phẩm/dự án phù hợp."})

    return json.dumps(result, ensure_ascii=False, indent=2)

# ===
