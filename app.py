import os
import json
import threading
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

# ===================== CONFIG =====================
CHAT_MODEL = "gpt-4o-mini"
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
TEMPERATURE = 0.25
MAX_TOKENS = 200

# 🔹 API Apps Script (Page Nhà)
API_USER_NOTES = "https://script.google.com/macros/s/AKfycbwGzvGaTN0Ui96QUgQbQcEGqvesomGwgbSMOOCoJ_O7250EqIdNWAaz9UmYB0SpBqhk/exec"
API_NOTES_NHA  = "https://script.google.com/macros/s/AKfycbwGzvGaTN0Ui96QUgQbQcEGqvesomGwgbSMOOCoJ_O7250EqIdNWAaz9UmYB0SpBqhk/exec"

# 🔹 PAGE IDs
PAGE_ID_NHA = "813440285194304"     # Page Nhà
PAGE_ID_CTT = "847842948414951"     # Page Thời trang
PAGE_ID_OC  = "895305580330861"     # Page Quán ốc

# 🔹 Tokens của các page
PAGE_TOKEN_MAP = {
    PAGE_ID_NHA: os.getenv("PAGE_TOKEN_NHA", ""),
    PAGE_ID_CTT: os.getenv("PAGE_TOKEN_CTT", ""),
    PAGE_ID_OC : os.getenv("PAGE_TOKEN_A", ""),
}

# 🔹 Gắn file JSON cho từng Page
JSON_FILE_MAP = {
    PAGE_ID_CTT: "a.json",   # Page thời trang
    PAGE_ID_OC : "b.json",   # Page quán ốc
}

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None


# ===================== JSON HANDLER =====================

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
    results = []

    for item in data:
        text_join = " ".join(str(v).lower() for v in item.values())
        if query in text_join:
            results.append(item)

    return results


# ===================== GOOGLE SHEET HANDLER =====================

def get_notes_from_user():
    try:
        r = requests.get(API_USER_NOTES, params={"action": "get"})
        return r.json().get("notes", [])
    except:
        return []


def get_notes_from_nha():
    try:
        r = requests.get(API_NOTES_NHA, params={"action": "get"})
        return r.json().get("notes", [])
    except:
        return []


# ===================== NOTE HANDLER =====================

def classify_note_category(text):
    n = text.lower()
    if any(k in n for k in ["giấy phép", "pháp lý", "xin phép"]): return "Giấy phép"
    if any(k in n for k in ["thiết kế", "phối cảnh", "cửa", "cad", "bản vẽ"]): return "Thiết kế"
    if any(k in n for k in ["móng", "thép", "cột", "d16", "d14", "dầm", "ép", "đổ"]): return "Thi công"
    if any(k in n for k in ["cửa", "sơn", "lát", "thiết bị", "nội thất", "gạch"]): return "Hoàn thiện"
    if any(k in n for k in ["bàn giao", "nghiệm thu"]): return "Bàn giao"
    if any(k in n for k in ["hoàn công", "sổ đỏ"]): return "Hoàn công"
    return "Chung"


def save_note_to_sheet(text, image_url=None):
    payload = {
        "action": "add",
        "text": text,
        "category": classify_note_category(text),
        "keywords": ", ".join([w.lower() for w in text.split() if len(w) >= 4]),
        "image_url": image_url or ""
    }
    try:
        requests.post(API_USER_NOTES, data=payload)
        return "Đã lưu ghi chú."
    except:
        return "Lỗi khi lưu ghi chú."


def edit_note_in_sheet(index, new_text):
    payload = {
        "action": "edit", "index": str(index),
        "text": new_text,
        "category": classify_note_category(new_text),
        "keywords": ", ".join([w.lower() for w in new_text.split() if len(w) >= 4])
    }
    try:
        requests.post(API_USER_NOTES, data=payload)
        return f"Đã sửa note {index}."
    except:
        return "Lỗi khi sửa ghi chú."


def delete_note_in_sheet(index):
    payload = {"action": "delete", "index": str(index)}
    try:
        requests.post(API_USER_NOTES, data=payload)
        return f"Đã xóa note {index}."
    except:
        return "Lỗi khi xóa ghi chú."


# ===================== AI FALLBACK =====================

def ask_llm(text):
    if not client:
        return "AI chưa sẵn sàng."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": "Trả lời rõ ràng, dễ hiểu."},
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, tôi chưa rõ."


# ===================== SEARCH HELPERS =====================

def search_in_notes_nha(query, notes_nha):
    query = query.lower()
    return [item for item in notes_nha if query in str(item).lower()]

def search_in_user_notes(query, notes_user):
    query = query.lower()
    return [item for item in notes_user if query in str(item).lower()]


# ===================== SMART REPLY =====================

def get_smart_reply(text, image_url=None, page_id=None):
    t = text.lower().strip()

    # ====== PAGE NHÀ (GIỮ NGUYÊN LOGIC) ======
    if page_id == PAGE_ID_NHA:

        if t in ["xem note", "xem ghi chú", "xem ghi chu", "notes"]:
            notes = get_notes_from_user()
            if not notes:
                return "Chưa có ghi chú nào."
            reply = "📘 Ghi chú đã lưu:\n\n"
            for i, n in enumerate(notes, 1):
                reply += f"{i}. ({n.get('category', 'Chung')}) {n.get('text', '')}\n"
            return reply.strip()

        if t.startswith(("note:", "ghi nhớ:", "ghi nho:", "thêm:", "them:", "lưu:", "luu:")):
            pure = text.split(":", 1)[1].strip()
            return save_note_to_sheet(pure, image_url)

        if t.startswith(("sửa note", "sua note")):
            try:
                idx = int(text.split()[2])
                new_text = text.split(":", 1)[1].strip()
                return edit_note_in_sheet(idx, new_text)
            except:
                return "Cú pháp đúng: sửa note 2: nội dung mới"

        if t.startswith(("xóa note", "xoá note", "xoa note")):
            try:
                idx = int([w for w in t.split() if w.isdigit()][0])
                return delete_note_in_sheet(idx)
            except:
                return "Cú pháp đúng: xóa note 3"

        notes_nha = get_notes_from_nha()
        found_nha = search_in_notes_nha(t, notes_nha)
        if found_nha:
            reply = "📌 Thông tin từ vật tư / thi công:\n\n"
            for item in found_nha[:3]:
                reply += (
                    f"📌 *{item.get('hang_muc', '')}*\n"
                    f"🔹 Chi tiết: {item.get('chi_tiet', '')}\n"
                    f"🏷 Thương hiệu: {item.get('thuong_hieu', '')}\n"
                    f"📏 Đơn vị: {item.get('don_vi', '')}\n"
                    f"📝 Ghi chú: {item.get('ghi_chu', '')}\n\n"
                )
            return reply.strip()

        notes_user = get_notes_from_user()
        found_user = search_in_user_notes(t, notes_user)
        if found_user:
            reply = "🗂 *Thông tin từ ghi chú cá nhân:*\n\n"
            for item in found_user[:3]:
                reply += f"• {item.get('text', '')}\n"
            return reply.strip()

        return ask_llm(text)

    # ====== PAGE JSON (THỜI TRANG, QUÁN ỐC) ======
    if page_id in JSON_FILE_MAP:
        found = search_products_json(t, page_id)
        if found:
            reply = "📦 Kết quả tìm thấy:\n\n"
            for item in found[:5]:
                for key, value in item.items():
                    reply += f"{key}: {value}\n"
                reply += "\n"
            return reply.strip()
        return "❌ Không tìm thấy trong dữ liệu."

    return ask_llm(text)


# ===================== FACEBOOK CONNECTOR =====================

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


# ===================== WEBHOOK =====================

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
