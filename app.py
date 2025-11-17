# app.py - MULTI-PAGE CHATBOT (NO RAG) - Trigger matching + LLM
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

# MULTI TOKEN FOR MULTI PAGES
PAGE_TOKEN_MAP = {
    "895305580330861": os.environ.get("PAGE_TOKEN_XYZ", ""),
    "847842948414951": os.environ.get("PAGE_TOKEN_CTT", "")
}

# PAGE → FOLDER
PAGE_DATASET_MAP = {
    "895305580330861": "page_xyz",
    "847842948414951": "page_ctt"
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
            print(f"❌ Error loading file {f}: {e}")

    print(f"📂 Loaded data for {folder}: {list(db.keys())}")
    return db

def build_system_prompt_for_folder(folder):
    db = DATABASE.get(folder, {})
    persona = {}
    for fk, content in db.items():
        persona = content.get("persona", {}) or persona
        if persona:
            break

    role = persona.get("role", "Trợ lý AI")
    tone = persona.get("tone", "Thân thiện, nhanh nhạy, chuyên nghiệp.")
    goal = persona.get("goal", "Hỗ trợ khách hàng.")

    prompt = (
        f"Bạn là {role}. Tone: {tone}\n"
        f"Goal: {goal}\n\n"
        "QUY TẮC:\n"
        "1) Ưu tiên trả lời theo trigger (keywords).\n"
        "2) Trả lời rõ ràng, tự nhiên.\n"
        "3) Nếu không chắc, hỏi lại để làm rõ.\n"
        "4) Không bịa thông tin chi tiết.\n"
    )
    return prompt

# -----------------------
# TRIGGER MATCHING
# -----------------------
def normalize_text(t):
    return (t or "").strip().lower()

def find_trigger_response(folder, text):
    """
    Return (response, no_trim_flag)
    Greeting và tất cả trigger → KHÔNG TRIM
    """
    t = normalize_text(text)
    db = DATABASE.get(folder, {})

    # Exact match
    for fk, data in db.items():
        for tr in data.get("chatbot_triggers", []):
            kws = sorted(tr.get("keywords", []), key=lambda x: -len(x))
            for k in kws:
                k_l = k.strip().lower()
                if not k_l:
                    continue

                if (
                    k_l == t
                    or f" {k_l} " in f" {t} "
                    or t.startswith(k_l + " ")
                    or t.endswith(" " + k_l)
                ):
                    resp = tr.get("response", "")
                    no_trim = True  # **CÁCH 3: Không trim tất cả trigger**
                    return choose_response_variant(resp), no_trim

    # Token fallback
    for fk, data in db.items():
        for tr in data.get("chatbot_triggers", []):
            for k in tr.get("keywords", []):
                k_tokens = [tok for tok in normalize_text(k).split() if tok]
                if all(tok in t for tok in k_tokens) and k_tokens:
                    resp = tr.get("response", "")
                    no_trim = True
                    return choose_response_variant(resp), no_trim

    return None, False

def choose_response_variant(resp):
    if isinstance(resp, list):
        return random.choice(resp)
    return resp

# -----------------------
# LLM + TRIM MỀM
# -----------------------
def soft_trim(text, max_len=350):
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."

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
    except Exception as e:
        print("❌ LLM error:", e)
        return "Hệ thống đang tạm bận, vui lòng thử lại sau."

# -----------------------
# SMART REPLY
# -----------------------
def ensure_folder_loaded(folder):
    if folder not in DATABASE:
        DATABASE[folder] = load_dataset_by_folder(folder)
        SYSTEM_PROMPTS[folder] = build_system_prompt_for_folder(folder)

def get_smart_reply(folder, text):
    ensure_folder_loaded(folder)

    # 1) TRIGGER → KHÔNG TRIM
    resp, no_trim = find_trigger_response(folder, text)
    if resp:
        return resp  # **CÁCH 3: Không trim trigger**

    # 2) LLM FALLBACK → Trim nhẹ để không nói quá dài
    sys_prompt = SYSTEM_PROMPTS.get(folder) or build_system_prompt_for_folder(folder)
    sys_prompt += "\nNOTE: Trả lời tự nhiên, rõ ràng, tối đa 3 câu."
    llm_ans = ask_llm(sys_prompt, text)
    return soft_trim(llm_ans)

# -----------------------
# FACEBOOK SEND
# -----------------------
def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        print("❌ Missing token for page:", page_id)
        return

    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
    payload = {"recipient": {"id": psid}, "message": {"text": text}}

    try:
        r = requests.post(url, json=payload, timeout=10)
        print("📨 FB Send:", r.status_code, r.text)
    except Exception as e:
        print("❌ FB send error:", e)

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
    data = request.get_json(silent=True) or {}

    for entry in data.get("entry", []):
        page_id = str(entry.get("id"))
        folder = PAGE_DATASET_MAP.get(page_id)
        if not folder:
            print("⚠️ Page không được cấu hình:", page_id)
            continue

        for evt in entry.get("messaging", []):
            if evt.get("message", {}).get("is_echo"):
                continue

            psid = evt.get("sender", {}).get("id")
            text = evt.get("message", {}).get("text")
            if psid and text:
                print(f"🌐 [{folder}] User {psid}: {text}")
                reply = get_smart_reply(folder, text)
                threading.Thread(target=send_text, args=(page_id, psid, reply)).start()

    return "OK", 200

# -----------------------
# HEALTH CHECK
# -----------------------
@app.route("/health")
def health():
    result = {}
    for page_id, folder in PAGE_DATASET_MAP.items():
        loaded = folder in DATABASE and bool(DATABASE[folder])
        result[page_id] = {"folder": folder, "loaded": loaded}
    return jsonify(ok=True, pages=result)

# -----------------------
# STARTUP
# -----------------------
def initial_load():
    for folder in set(PAGE_DATASET_MAP.values()):
        DATABASE[folder] = load_dataset_by_folder(folder)
        SYSTEM_PROMPTS[folder] = build_system_prompt_for_folder(folder)

if __name__ == "__main__":
    initial_load()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
