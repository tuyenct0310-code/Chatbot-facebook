# app.py - MULTI-PAGE CHATBOT (NO RAG) - Trigger + JSON + GoogleSheets + Dynamic Notes
import os
import json
import random
import time
import threading
import requests
from pathlib import Path
from flask import Flask, request, jsonify
from openai import OpenAI

# -----------------------
# CONFIG
# -----------------------
CHAT_MODEL = "gpt-4o-mini"
TEMPERATURE = 0.25
MAX_TOKENS_REPLY = 200
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

# FB PAGE TOKEN MAPPING
PAGE_TOKEN_MAP = {
    "895305580330861": os.environ.get("PAGE_TOKEN_A", ""),  
    "847842948414951": os.environ.get("PAGE_TOKEN_CTT", ""),  
    "813440285194304": os.environ.get("PAGE_TOKEN_NHA", "")     
}

# PAGE → DATASET FOLDER
PAGE_DATASET_MAP = {
    "895305580330861": "page_A",
    "847842948414951": "page_ctt",
    "813440285194304": "page_NHA"  
}

# PAGE → SOURCE TYPE (json / json+sheet)
PAGE_DATA_SOURCE = {
    "895305580330861": "json",
    "847842948414951": "json+sheet",
    "813440285194304": "json"  
}

# SHEET ID (chỉ nếu dùng Google Sheet)
PAGE_SHEET_ID = {
    "847842948414951": os.environ.get("SHEET_ID_CTT", "")
}

DATA_FOLDER_ROOT = Path("data")

app = Flask(__name__)

# -----------------------
# OpenAI Client
# -----------------------
try:
    client = OpenAI(api_key=OPENAI_KEY)
    print("✅ OpenAI client ready")
except Exception as e:
    print("❌ OpenAI init error:", e)
    client = None

# -----------------------
# GLOBAL STORAGE
# -----------------------
DATABASE = {}
SYSTEM_PROMPTS = {}

# -----------------------
# LOAD DATA
# -----------------------
def load_dataset_by_folder(folder):
    folder_path = DATA_FOLDER_ROOT / folder
    db = {}
    if not folder_path.exists():
        print(f"❌ Missing dataset folder: data/{folder}")
        return db

    for f in folder_path.glob("*.json"):
        try:
            with open(f, "r", encoding="utf8") as fh:
                db[f.stem] = json.load(fh)
        except Exception as e:
            print(f"❌ Error loading {f}: {e}")

    print(f"📂 Loaded data for {folder}: {list(db.keys())}")
    return db

def build_system_prompt_for_folder(folder):
    return "Bạn là trợ lý xây dựng, trả lời rõ ràng, thực tế, ưu tiên checklist, không nói dài."

def normalize_text(t):
    return (t or "").strip().lower()

def find_trigger_response(folder, text):
    t = normalize_text(text)
    db = DATABASE.get(folder, {})
    for fk, data in db.items():
        for tr in data.get("chatbot_triggers", []):
            for kw in tr.get("keywords", []):
                if kw.lower() in t:
                    return tr.get("response", ""), True
    return None, False

def ask_llm(system_prompt, user_text):
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS_REPLY
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, hệ thống đang bận."

def load_sheet_data(sheet_id):
    try:
        import gspread
        gc = gspread.service_account(filename='credentials.json')
        sh = gc.open_by_key(sheet_id)
        ws = sh.sheet1
        rows = ws.get_all_records()
        return [
            {
                "id": row.get("id") or "",
                "category": row.get("category") or "",
                "text": row.get("detail") or row.get("answer") or "",
                "keywords": [k.strip().lower() for k in row.get("keywords", "").split(",") if k.strip()]
            }
            for row in rows
        ]
    except Exception as e:
        print("❌ Sheet load error:", e)
        return []

def merge_data(json_data, sheet_data):
    return list(json_data) + sheet_data

def detect_note(text):
    t = text.lower().strip()
    for p in ["note:", "ghi nhớ:", "thêm:", "lưu ý:", "cập nhật:"]:
        if t.startswith(p):
            return text[len(p):].strip()
    return None

def save_note_to_json(folder, note_text):
    folder_path = DATA_FOLDER_ROOT / folder
    notes_file = folder_path / "user_notes.json"

    if not notes_file.exists():
        with open(notes_file, "w", encoding="utf-8") as f:
            json.dump({"knowledge": []}, f, ensure_ascii=False, indent=2)

    with open(notes_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    new_entry = {
        "id": f"user_{len(data['knowledge'])+1}",
        "text": note_text,
        "category": "user_note",
        "keywords": [],
        "date_added": time.strftime("%Y-%m-%d")
    }
    data["knowledge"].append(new_entry)

    with open(notes_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("📝 Note saved:", new_entry)

def ensure_folder_loaded(folder):
    if folder not in DATABASE:
        DATABASE[folder] = load_dataset_by_folder(folder)
        SYSTEM_PROMPTS[folder] = build_system_prompt_for_folder(folder)

def get_smart_reply(folder, text, page_id):
    ensure_folder_loaded(folder)

    # 1️⃣ NOTE Detection
    note_text = detect_note(text)
    if note_text:
        save_note_to_json(folder, note_text)
        return "Đã ghi chú, lần sau hỏi tôi sẽ nhớ."

    # 2️⃣ Load static JSON triggers
    json_data = []
    for fk, content in DATABASE.get(folder, {}).items():
        if "chatbot_triggers" in content:
            for tr in content["chatbot_triggers"]:
                json_data.append({
                    "text": tr.get("response", ""),
                    "keywords": [k.lower() for k in tr.get("keywords", [])]
                })

    # 3️⃣ Load dynamic Notes
    notes_file = DATA_FOLDER_ROOT / folder / "user_notes.json"
    if notes_file.exists():
        with open(notes_file, "r", encoding="utf-8") as f:
            json_data.extend(json.load(f).get("knowledge", []))

    # 4️⃣ Load Sheet (for pages using JSON+Sheet)
    sheet_data = []
    if PAGE_DATA_SOURCE.get(page_id) == "json+sheet":
        sheet_id = PAGE_SHEET_ID.get(page_id)
        if sheet_id:
            sheet_data = load_sheet_data(sheet_id)

    combined_data = merge_data(json_data, sheet_data)

    # 5️⃣ Try keyword matching
    t = text.lower()
    for item in combined_data:
        for kw in item.get("keywords", []):
            if kw in t:
                return item["text"]

    # 6️⃣ LLM Fallback
    return ask_llm(SYSTEM_PROMPTS.get(folder), text)

# -----------------------
# FACEBOOK SEND
# -----------------------
def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        return
    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    payload = {"recipient": {"id": psid}, "message": {"text": text}}
    requests.post(url, json=payload)

# -----------------------
# WEBHOOK
# -----------------------
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Sai verify token", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json() or {}
    for entry in data.get("entry", []):
        page_id = str(entry.get("id"))
        folder = PAGE_DATASET_MAP.get(page_id)
        for evt in entry.get("messaging", []):
            psid = evt.get("sender", {}).get("id")
            text = evt.get("message", {}).get("text")
            if psid and text:
                threading.Thread(
                    target=send_text, 
                    args=(page_id, psid, get_smart_reply(folder, text, page_id))
                ).start()
    return "OK", 200

# -----------------------
# HEALTH CHECK
# -----------------------
@app.route("/health")
def health():
    return jsonify(ok=True, pages=list(PAGE_DATASET_MAP.keys()))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

