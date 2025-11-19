# app.py - MULTI-PAGE CHATBOT with Notes (Smart Category, View, Edit)
import os
import json
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

PAGE_TOKEN_MAP = {
    "895305580330861": os.environ.get("PAGE_TOKEN_A", ""),
    "847842948414951": os.environ.get("PAGE_TOKEN_CTT", ""),
    "813440285194304": os.environ.get("PAGE_TOKEN_NHA", "")
}

PAGE_DATASET_MAP = {
    "895305580330861": "page_A",
    "847842948414951": "page_ctt",
    "813440285194304": "page_NHA"
}

PAGE_DATA_SOURCE = {
    "895305580330861": "json",
    "847842948414951": "json+sheet",
    "813440285194304": "json"
}

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
except Exception:
    client = None
    print("❌ OpenAI init error")

# -----------------------
# GLOBAL
# -----------------------
DATABASE = {}
SYSTEM_PROMPTS = {}

# -----------------------
# Load dataset
# -----------------------
def load_dataset_by_folder(folder):
    folder_path = DATA_FOLDER_ROOT / folder
    db = {}
    if not folder_path.exists():
        print(f"⚠ Folder not found: data/{folder}")
        return db
    for f in folder_path.glob("*.json"):
        try:
            with open(f, "r", encoding="utf8") as fh:
                db[f.stem] = json.load(fh)
        except Exception as e:
            print(f"❌ Error loading {f}: {e}")
    print(f"📂 Loaded: {list(db.keys())}")
    return db

def build_system_prompt_for_folder(folder):
    return "Bạn là trợ lý xây dựng. Trả lời rõ ràng, thực tế, ưu tiên checklist, không nói dài."

# -----------------------
# Sheet load
# -----------------------
def load_sheet_data(sheet_id):
    try:
        import gspread
        gc = gspread.service_account(filename='credentials.json')
        ws = gc.open_by_key(sheet_id).sheet1
        rows = ws.get_all_records()
        return [{
            "text": r.get("answer") or r.get("detail") or "",
            "keywords": [k.strip().lower() for k in r.get("keywords", "").split(",") if k.strip()],
            "category": r.get("category","Chung")
        } for r in rows]
    except Exception as e:
        print("❌ Sheet load error:", e)
        return []

def merge_data(a,b): return list(a)+list(b)

# -----------------------
# AI fallback
# -----------------------
def ask_llm(system_prompt, text):
    if not client:
        return "Hệ thống chưa sẵn sàng."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role":"system","content":system_prompt},{"role":"user","content":text}],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS_REPLY
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, hệ thống đang bận."

# -----------------------
# NOTE FUNCTIONS
# -----------------------
def classify_note_category(note):
    n = note.lower()
    if any(k in n for k in ["giấy phép", "pháp lý", "xin phép", "ủy ban"]): return "Giấy phép"
    if any(k in n for k in ["thiết kế", "bản vẽ", "3d", "auto", "phối cảnh"]): return "Thiết kế"
    if any(k in n for k in ["móng", "cột", "thép", "đổ mái", "thi công"]): return "Thi công"
    if any(k in n for k in ["cửa", "lát", "sơn", "nội thất", "thiết bị vệ sinh"]): return "Hoàn thiện"
    return "Chung"

def save_note(folder, text):
    notes_file = DATA_FOLDER_ROOT / folder / "user_notes.json"
    if not notes_file.exists():
        with open(notes_file, "w", encoding="utf-8") as f:
            json.dump({"knowledge":[]}, f, indent=2, ensure_ascii=False)

    with open(notes_file,"r",encoding="utf-8") as f:
        data = json.load(f)

    entry = {
        "id": f"user_{len(data['knowledge'])+1}",
        "text": text,
        "category": classify_note_category(text),
        "keywords": [w.lower() for w in text.split() if len(w)>=4],
        "date_added": time.strftime("%Y-%m-%d")
    }
    data["knowledge"].append(entry)

    with open(notes_file,"w",encoding="utf-8") as f:
        json.dump(data,f,indent=2,ensure_ascii=False)

    print("📝 Note saved ->", entry)

def get_all_notes(folder):
    notes_file = DATA_FOLDER_ROOT / folder / "user_notes.json"
    if not notes_file.exists():
        return "Chưa có ghi chú nào."
    with open(notes_file,"r",encoding="utf-8") as f:
        notes = json.load(f).get("knowledge", [])
    if not notes:
        return "Chưa có ghi chú nào."
    reply = "📘 Ghi chú đã lưu:\n\n"
    for i,n in enumerate(notes,1):
        reply += f"{i}. ({n['category']}) {n['text']}\n"
    return reply

def get_notes_by_category(folder, cat):
    notes_file = DATA_FOLDER_ROOT / folder / "user_notes.json"
    if not notes_file.exists(): 
        return "Chưa có ghi chú nào."
    with open(notes_file,"r",encoding="utf-8") as f:
        notes = json.load(f).get("knowledge", [])
    filtered = [n for n in notes if n['category'].lower()==cat.lower()]
    if not filtered: 
        return f"Chưa có ghi chú mục {cat}."
    reply = f"📘 Ghi chú mục {cat}:\n\n"
    for i,n in enumerate(filtered,1):
        reply += f"{i}. {n['text']}\n"
    return reply

def edit_note(folder, index, new_text):
    notes_file = DATA_FOLDER_ROOT / folder / "user_notes.json"
    if not notes_file.exists(): 
        return "Chưa có ghi chú nào."

    with open(notes_file,"r",encoding="utf-8") as f:
        data = json.load(f)

    lst = data.get("knowledge", [])
    if 1<=index<=len(lst):
        lst[index-1]["text"] = new_text
        lst[index-1]["category"] = classify_note_category(new_text)
        lst[index-1]["keywords"] = [w.lower() for w in new_text.split() if len(w)>=4]

        with open(notes_file,"w",encoding="utf-8") as f:
            json.dump(data,f,indent=2,ensure_ascii=False)
        return f"Đã sửa Note {index}."
    return f"Không tìm thấy Note số {index}."

# -----------------------
# SMART REPLY
# -----------------------
def ensure_folder_loaded(folder):
    if folder not in DATABASE:
        DATABASE[folder] = load_dataset_by_folder(folder)
        SYSTEM_PROMPTS[folder] = build_system_prompt_for_folder(folder)

def get_smart_reply(folder, text, page_id):
    ensure_folder_loaded(folder)

    # ---- Note detection ----
    if text.lower().startswith(("note:","ghi nhớ:","cập nhật:","thêm:")):
        pure = text.split(":",1)[1].strip()
        save_note(folder, pure)
        return "Đã ghi chú, lần sau hỏi tôi sẽ nhớ."

    # ---- Xem toàn bộ Note ----
    if text.lower().strip() in ["xem note","xem ghi chú","xem tất cả note","notes"]:
        return get_all_notes(folder)

    # ---- Xem Note theo MỤC ----
    category_map = {
        "thi công":"Thi công", "giấy phép":"Giấy phép",
        "thiết kế":"Thiết kế", "hoàn thiện":"Hoàn thiện",
        "chung":"Chung"
    }
    for k,v in category_map.items():
        if text.lower().startswith(f"xem note {k}"):
            return get_notes_by_category(folder, v)

    # ---- Sửa Note ----
    if text.lower().startswith("sửa note"):
        try:
            parts = text.split(":",1)
            idx = int(parts[0].split()[2])
            new_text = parts[1].strip()
            return edit_note(folder, idx, new_text)
        except:
            return "Cú pháp đúng: Sửa note 2: nội dung mới"

    # ---- Continue normal logic ----
    # Load triggers
    json_data = []
    for fk,content in DATABASE.get(folder,{}).items():
        for tr in content.get("chatbot_triggers", []):
            json_data.append({
                "text": tr.get("response",""),
                "keywords": [k.lower() for k in tr.get("keywords",[])]
            })

    # Load Notes
    notes_file = DATA_FOLDER_ROOT / folder / "user_notes.json"
    if notes_file.exists():
        with open(notes_file,"r",encoding="utf-8") as f:
            json_data.extend(json.load(f).get("knowledge", []))

    # Load Sheet if any
    sheet_data = []
    if PAGE_DATA_SOURCE.get(page_id)=="json+sheet" and PAGE_SHEET_ID.get(page_id):
        sheet_data = load_sheet_data(PAGE_SHEET_ID[page_id])

    combined = merge_data(json_data, sheet_data)

    # Smart match by keywords
    t = text.lower()
    best = None
    max_hits = 0
    for item in combined:
        hits = sum(1 for kw in item.get("keywords",[]) if kw in t)
        if hits>max_hits:
            max_hits = hits
            best = item
    if best:
        return best["text"]

    # AI fallback
    return ask_llm(SYSTEM_PROMPTS.get(folder), text)

# -----------------------
# FB Send
# -----------------------
def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        return
    requests.post(
        f"https://graph.facebook.com/v19.0/me/messages?access_token={token}",
        json={"recipient":{"id":psid},"message":{"text":text}}
    )

# -----------------------
# Webhook
# -----------------------
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token")==VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Sai verify token",403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json() or {}
    for entry in data.get("entry",[]):
        page_id = str(entry.get("id"))
        folder = PAGE_DATASET_MAP.get(page_id)
        for evt in entry.get("messaging",[]):
            psid = evt.get("sender",{}).get("id")
            text = evt.get("message",{}).get("text")
            if psid and text:
                reply = get_smart_reply(folder, text, page_id)
                threading.Thread(target=send_text,args=(page_id,psid,reply)).start()
    return "OK",200

# -----------------------
# Health
# -----------------------
@app.route("/health")
def health():
    return jsonify(ok=True, pages=list(PAGE_DATASET_MAP.keys()))

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",8080)))
