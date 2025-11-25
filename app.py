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

# ============== Page Data Config ==============
API_SHEET_MAP = {
    "847842948414951": None,  # Page Thời trang (chỉ JSON)
    "895305580330861": None,  # Page Quán ốc (chỉ JSON)
    "813440285194304": "https://script.google.com/macros/s/AKfycbwGzvGaTN0Ui96QUgQbQcEGqvesomGwgbSMOOCoJ_O7250EqIdNWAaz9UmYB0SpBqhk/exec"
}

JSON_FILE_MAP = {
    "847842948414951": "a.json",  # Page Thời trang
    "895305580330861": "b.json",  # Page Quán ốc
    "813440285194304": None       # Page Nhà không dùng JSON
}

PAGE_ID_NHA = "813440285194304"

PAGE_TOKEN_MAP = {
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", ""),
    "847842948414951": os.getenv("PAGE_TOKEN_CTT", ""),
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),
}

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None


# ========= GENERIC JSON HANDLER ==========
def load_page_json(page_id):
    file_name = JSON_FILE_MAP.get(page_id)
    if not file_name:
        return []
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def search_products_json(query, page_id):
    data = load_page_json(page_id)
    query = query.lower()
    return [item for item in data if query in str(item).lower()]


# ========= AI FALLBACK ==========
def ask_llm(text):
    if not client:
        return "AI đang tạm không dùng được."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": "Trả lời ngắn gọn, chính xác."},
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, tôi chưa hiểu."


# ========= PAGE NHA: GHI CHÚ & VẬT TƯ ==========
def get_notes_from_user():
    try:
        r = requests.get(API_SHEET_MAP[PAGE_ID_NHA], params={"action": "get", "sheet": "User_Notes"})
        return r.json().get("notes", [])
    except:
        return []


def get_notes_from_nha():
    try:
        r = requests.get(API_SHEET_MAP[PAGE_ID_NHA], params={"action": "get", "sheet": "Notes_Nha"})
        return r.json().get("notes", [])
    except:
        return []


def save_note_to_sheet(text, image_url=None):
    payload = {
        "action": "add",
        "sheet": "User_Notes",
        "text": text,
        "image_url": image_url or "",
        "keywords": ", ".join([w for w in text.split() if len(w) >= 3]),
    }
    requests.post(API_SHEET_MAP[PAGE_ID_NHA], data=payload)
    return "Đã lưu ghi chú."


def get_reply_for_page_nha(text, image_url=None):
    t = text.lower().strip()

    # Xem ghi chú cá nhân
    if t in ["xem note", "xem ghi chú", "notes"]:
        notes = get_notes_from_user()
        if not notes:
            return "📭 Chưa có ghi chú nào."
        reply = "📘 Ghi chú của bạn:\n\n"
        for i, n in enumerate(notes, 1):
            reply += (
                f"{i}. 📝 {n.get('text', '')}\n"
                f"   📂 Loại: {n.get('category', '')}\n"
                f"   ⏱ Thời gian: {n.get('date_added', '')}\n"
                f"   🔑 Keywords: {n.get('keywords', '')}\n"
                f"   🖼 Hình ảnh: {n.get('image_url', '')}\n\n"
            )
        return reply.strip()

    # Lưu ghi chú
    if t.startswith(("note:", "ghi nhớ:", "ghi chu:", "lưu:")):
        return save_note_to_sheet(text.split(":", 1)[1].strip(), image_url)

    # Tìm vật tư
    notes_nha = get_notes_from_nha()
    found = [item for item in notes_nha if t in str(item).lower()]
    if found:
        reply = "📌 Thông tin vật tư:\n\n"
        for item in found[:3]:
            reply += (
                f"🏷 {item.get('hang_muc', '')}\n"
                f"🔹 {item.get('chi_tiet', '')}\n"
                f"📏 {item.get('don_vi', '')}\n"
                f"💡 {item.get('ghi_chu', '')}\n\n"
            )
        return reply.strip()

    return ask_llm(text)


# ========= GENERIC SMART REPLY ==========
def get_smart_reply(text, image_url=None, page_id=None):

    # ===== PAGE NHÀ =====
    if page_id == PAGE_ID_NHA:
        return get_reply_for_page_nha(text, image_url)

    # ===== PAGE JSON SẢN PHẨM =====
    if page_id in ["847842948414951", "895305580330861"]:
        found = search_products_json(text, page_id)
        if found:
            reply = "📦 Sản phẩm tìm thấy:\n\n"
            for item in found[:3]:
                reply += "🛍 Sản phẩm:\n"
                for key, value in item.items():
                    reply += f"• {key}: {value}\n"
                reply += "\n"
            return reply.strip()
        return "❌ Không tìm thấy sản phẩm trong file."

    # ===== OFFICIAL AI FALLBACK =====
    return ask_llm(text)


# ========= FACEBOOK CONNECTOR ==========
def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        return
    requests.post(
        "https://graph.facebook.com/v19.0/me/messages",
        params={"access_token": token},
        json={"recipient": {"id": psid}, "message": {"text": text}}
    )


# ========= WEBHOOK ==========
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
            text = event.get("message", {}).get("text")
            if psid and text:
                reply = get_smart_reply(text, None, page_id)
                threading.Thread(target=send_text, args=(page_id, psid, reply)).start()
    return "OK", 200


@app.route("/health")
def health():
    return jsonify(status="running")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"Server chạy port {port}")
    app.run(host="0.0.0.0", port=port)
