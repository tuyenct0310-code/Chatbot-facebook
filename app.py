import os
import json
import threading
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

# ================= CONFIG ===================
CHAT_MODEL = "gpt-4o-mini"
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
TEMPERATURE = 0.25
MAX_TOKENS = 200

# 🔹 Mapping Page → API Google Sheet tương ứng
API_SHEET_MAP = {
    "847842948414951": "https://script.google.com/macros/s/AKfycbxiQt7qyLdeXtwSBqL5fS2yzZqbNRSTOaoYnly9LqpfAwxzqVh_tQ03TTHwF8livVfkIQ/exec",  # Page Thời trang
    "895305580330861": None,  # Page Quán ốc
    "813440285194304": "https://script.google.com/macros/s/AKfycbwGzvGaTN0Ui96QUgQbQcEGqvesomGwgbSMOOCoJ_O7250EqIdNWAaz9UmYB0SpBqhk/exec"      # Page Nhà
}

# 🔹 Mapping Page → File JSON tương ứng
JSON_FILE_MAP = {
    "847842948414951": "a.json",   # Page Thời trang
    "895305580330861": "b.json",   # Page Quán ốc
    "813440285194304": None        # Page Nhà không dùng JSON
}

# 🔹 Page list
PAGE_ID_NHA = "813440285194304"

PAGE_TOKEN_MAP = {
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", ""),
    "847842948414951": os.getenv("PAGE_TOKEN_CTT", ""),
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),
}

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None


# ============== JSON LOADER ================
def load_page_json(page_id):
    file_name = JSON_FILE_MAP.get(page_id)
    if not file_name:
        return []
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Lỗi đọc JSON {file_name}:", e)
        return []


def search_products_json(query, page_id):
    data = load_page_json(page_id)
    query = query.lower()
    results = []

    for item in data:
        if query in item.get("ten", "").lower() or query in item.get("mo_ta", "").lower():
            results.append(item)
    return results


# ======== GOOGLE SHEET HANDLER ==========
def get_sheet_data(page_id):
    api = API_SHEET_MAP.get(page_id)
    if not api:
        return []
    try:
        r = requests.get(api, params={"action": "get", "sheet": "Products"})
        return r.json().get("notes", [])
    except Exception as e:
        print(f"Lỗi get_sheet_data({page_id}):", e)
        return []


def search_sheet_data(query, page_id):
    data = get_sheet_data(page_id)
    query = query.lower()
    results = []

    for item in data:
        if query in str(item).lower():
            results.append(item)
    return results


# ======== AI FALLBACK ==========
def ask_llm(text):
    if not client:
        return "AI chưa sẵn sàng."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": "Bạn là trợ lý thông minh, trả lời rõ ràng, chính xác."},
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, tôi chưa rõ."


# ========= SMART REPLY ==========
def get_smart_reply(text, image_url=None, page_id=None):
    t = text.lower().strip()

    # ===== PAGE Nhà xử lý riêng (ghi chú + Notes_Nha) ======
    if page_id == PAGE_ID_NHA:
        return ask_llm(text)  # giữ nguyên logic cũ (đã có bên trên)

    # ===== PAGE sản phẩm (JSON + Google Sheet) ======
    if page_id in ["847842948414951", "895305580330861"]:
        found = search_products_json(t, page_id)
        if not found:
            found = search_sheet_data(t, page_id)

        if found:
            reply = "📦 Sản phẩm bạn tìm:\n\n"
            for item in found[:3]:
                reply += (
                    f"🛍 {item.get('ten', '')}\n"
                    f"💰 Giá: {item.get('gia', '')}\n"
                    f"📏 Size/Đơn vị: {item.get('size', item.get('don_vi', ''))}\n"
                    f"ℹ️ {item.get('mo_ta', '')}\n\n"
                )
            return reply.strip()

        return "❌ Không tìm thấy sản phẩm trong dữ liệu."

    # ===== Page khác → fallback AI =====
    return ask_llm(text)


# ========= FACEBOOK CONNECTOR ==========
def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        print("Không có PAGE_TOKEN cho page", page_id)
        return
    try:
        requests.post(
            "https://graph.facebook.com/v19.0/me/messages",
            params={"access_token": token},
            json={"recipient": {"id": psid}, "message": {"text": text}}
        )
    except Exception as e:
        print("Lỗi send_text:", e)


# ======== WEBHOOK ==========
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Sai verify token", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json() or {}

    for entry in data.get("entry", []):
        page_id = entry.get("id")
        for event in entry.get("messaging", []):
            psid = event.get("sender", {}).get("id")
            msg = event.get("message", {}) or {}
            text = msg.get("text")

            if psid and text:
                reply = get_smart_reply(text, None, page_id)
                threading.Thread(target=send_text, args=(page_id, psid, reply)).start()

    return "OK", 200


@app.route("/health")
def health():
    return jsonify(status="running")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"Server chạy tại port {port}")
    app.run(host="0.0.0.0", port=port)
