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
    "895305580330861": None,  # Page Quán ốc dùng JSON, không dùng Sheet
    "813440285194304": "https://script.google.com/macros/s/AKfycbwGzvGaTN0Ui96QUgQbQcEGqvesomGwgbSMOOCoJ_O7250EqIdNWAaz9UmYB0SpBqhk/exec"   # Page Nhà (Notes_Nha + User_Notes)
}

# 🔹 Mapping Page → File JSON tương ứng
JSON_FILE_MAP = {
    "847842948414951": "a.json",  # Page Thời trang
    "895305580330861": "b.json",  # Page Quán ốc
    "813440285194304": None       # Page Nhà không dùng JSON
}

# 🔹 Dùng riêng cho Page Nhà
PAGE_ID_NHA = "813440285194304"

# 🔹 Token các Page
PAGE_TOKEN_MAP = {
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", ""),
    "847842948414951": os.getenv("PAGE_TOKEN_CTT", ""),
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),
}

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# ================== PAGE NHÀ (GHI CHÚ + NOTES_NHA) ===================
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
        "keywords": ", ".join([w for w in text.split() if len(w) >= 3])
    }
    try:
        requests.post(API_SHEET_MAP[PAGE_ID_NHA], data=payload)
        return "Đã lưu ghi chú."
    except:
        return "Lỗi khi lưu ghi chú."


def delete_note_in_sheet(index):
    payload = {"action": "delete", "sheet": "User_Notes", "index": str(index)}
    try:
        requests.post(API_SHEET_MAP[PAGE_ID_NHA], data=payload)
        return f"Đã xóa note {index}."
    except:
        return "Lỗi khi xóa ghi chú."


def search_in_notes_nha(query, notes_nha):
    results = []
    for item in notes_nha:
        if query in str(item).lower():
            results.append(item)
    return results


# ============== JSON LOADER ================
def load_page_json(page_id):
    file_name = JSON_FILE_MAP.get(page_id)
    if not file_name:
        return []
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def search_products_json(query, page_id):
    data = load_page_json(page_id)
    query = query.lower()
    return [item for item in data if query in str(item).lower()]


# ======== GOOGLE SHEET HANDLER ==========
def get_sheet_data(page_id):
    api = API_SHEET_MAP.get(page_id)
    if not api:
        return []
    try:
        r = requests.get(api, params={"action": "get", "sheet": "Products"})
        return r.json().get("notes", [])
    except:
        return []


def search_sheet_data(query, page_id):
    data = get_sheet_data(page_id)
    query = query.lower()
    return [item for item in data if query in str(item).lower()]


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


# ========= PAGE NHÀ PROCESSING ==========
def get_reply_for_page_nha(text, image_url=None):
    t = text.lower().strip()

    # Xem ghi chú
    if t in ["xem note", "xem ghi chú", "notes"]:
        notes = get_notes_from_user()
        if not notes:
            return "Chưa có ghi chú nào."
        reply = "📘 Ghi chú đã lưu:\n\n"
        for i, n in enumerate(notes, 1):
            reply += f"{i}. {n.get('text', '')}\n"
        return reply

    # Lưu ghi chú
    if t.startswith(("note:", "ghi nhớ", "ghi chu", "lưu:")):
        return save_note_to_sheet(text.split(":", 1)[1].strip(), image_url)

    # Tìm vật tư trong Notes_Nha
    notes_nha = get_notes_from_nha()
    found_nha = search_in_notes_nha(t, notes_nha)
    if found_nha:
        reply = "📌 Kết quả từ Notes_Nha:\n\n"
        for item in found_nha[:3]:
            reply += (
                f"🏷 *{item.get('hang_muc', '')}*\n"
                f"🔹 {item.get('chi_tiet', '')}\n"
                f"💡 {item.get('ghi_chu', '')}\n\n"
            )
        return reply.strip()

    return ask_llm(text)


# ========= SMART REPLY ==========
def get_smart_reply(text, image_url=None, page_id=None):
    t = text.lower().strip()

    # Page Nhà → xử lý riêng
    if page_id == PAGE_ID_NHA:
        return get_reply_for_page_nha(text, image_url)

    # Page sản phẩm (Quần áo / Quán ốc)
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
                    f"📏 Đơn vị: {item.get('don_vi', item.get('size', ''))}\n"
                    f"ℹ️ {item.get('mo_ta', '')}\n\n"
                )
            return reply.strip()

        return "❌ Không tìm thấy sản phẩm."

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
