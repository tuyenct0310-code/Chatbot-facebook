import os
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

# 🔹 API Apps Script
API_USER_NOTES = "https://script.google.com/macros/s/AKfycbwGzvGaTN0Ui96QUgQbQcEGqvesomGwgbSMOOCoJ_O7250EqIdNWAaz9UmYB0SpBqhk/exec"
API_NOTES_NHA  = "https://script.google.com/macros/s/AKfycbwGzvGaTN0Ui96QUgQbQcEGqvesomGwgbSMOOCoJ_O7250EqIdNWAaz9UmYB0SpBqhk/exec"

# 🔹 Tokens của các page
PAGE_TOKEN_MAP = {
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", ""),  # Page Nhà
    "847842948414951": os.getenv("PAGE_TOKEN_CTT", ""),  # Page thời trang
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),    # Page khác
}

PAGE_ID_NHA = "813440285194304"

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None


# ================= GOOGLE SHEET HANDLERS =================

def get_notes_from_user():
    try:
        r = requests.get(API_USER_NOTES, params={"action": "get"})
        print("User_Notes raw:", r.text)
        return r.json().get("notes", [])
    except Exception as e:
        print("Lỗi get_notes_from_user:", e)
        return []


def get_notes_from_nha():
    try:
        r = requests.get(API_NOTES_NHA, params={"action": "get"})
        print("Notes_Nha raw:", r.text)
        return r.json().get("notes", [])
    except Exception as e:
        print("Lỗi get_notes_from_nha:", e)
        return []


# ================= SAVE / EDIT / DELETE USER NOTES =================

def classify_note_category(text):
    n = text.lower()
    if any(k in n for k in ["giấy phép", "pháp lý", "xin phép"]):
        return "Giấy phép"
    if any(k in n for k in ["thiết kế", "phối cảnh", "cửa", "cad", "bản vẽ"]):
        return "Thiết kế"
    if any(k in n for k in ["móng", "thép", "cột", "d16", "d14", "dầm", "ép", "đổ"]):
        return "Thi công"
    if any(k in n for k in ["cửa", "sơn", "lát", "thiết bị", "nội thất", "gạch"]):
        return "Hoàn thiện"
    if any(k in n for k in ["bàn giao", "nghiệm thu"]):
        return "Bàn giao"
    if any(k in n for k in ["hoàn công", "sổ đỏ"]):
        return "Hoàn công"
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
    except Exception as e:
        print("Lỗi save_note_to_sheet:", e)
        return "Lỗi khi lưu ghi chú."


def edit_note_in_sheet(index, new_text):
    payload = {
        "action": "edit",
        "index": str(index),
        "text": new_text,
        "category": classify_note_category(new_text),
        "keywords": ", ".join([w.lower() for w in new_text.split() if len(w) >= 4]),
    }
    try:
        requests.post(API_USER_NOTES, data=payload)
        return f"Đã sửa note {index}."
    except Exception as e:
        print("Lỗi edit_note_in_sheet:", e)
        return "Lỗi khi sửa ghi chú."


def delete_note_in_sheet(index):
    payload = {"action": "delete", "index": str(index)}
    try:
        requests.post(API_USER_NOTES, data=payload)
        return f"Đã xóa note {index}."
    except Exception as e:
        print("Lỗi delete_note_in_sheet:", e)
        return "Lỗi khi xóa ghi chú."


# ================= AI FALLBACK =================

def ask_llm(text):
    if not client:
        return "AI chưa sẵn sàng."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system",
                 "content": "Bạn là trợ lý xây nhà, trả lời rõ ràng, thực tế, ngắn gọn."},
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("Lỗi ask_llm:", e)
        return "Xin lỗi, tôi chưa rõ."


# ================= SEARCH HELPERS =================

def search_in_notes_nha(query, notes_nha):
    results = []
    for item in notes_nha:
        kws = item.get("keywords", "").lower().split()
        if any(k in query for k in kws if len(k) >= 3):
            results.append(item)
    return results


def search_in_user_notes(query, notes_user):
    results = []
    for item in notes_user:
        kws = item.get("keywords", "").lower().replace(";", ",").split(",")
        if any(k.strip() in query for k in kws if len(k.strip()) >= 3):
            results.append(item)
    return results


# ================= SMART REPLY =================

def get_smart_reply(text, image_url=None, page_id=None):
    t = text.lower().strip()

    if page_id != PAGE_ID_NHA:
        return ask_llm(text)

    # Xem note
    if t in ["xem note", "xem ghi chú", "xem ghi chu", "notes"]:
        notes = get_notes_from_user()
        if not notes:
            return "Chưa có ghi chú nào."
        reply = "📘 Ghi chú đã lưu:\n\n"
        for i, n in enumerate(notes, 1):
            reply += f"{i}. ({n.get('category', 'Chung')}) {n.get('text', '')}\n"
        return reply.strip()

    # Lưu note
    if t.startswith(("note:", "ghi nhớ:", "ghi nho:", "thêm:", "them:", "lưu:", "luu:")):
        pure = text.split(":", 1)[1].strip()
        return save_note_to_sheet(pure, image_url)

    # Sửa note
    if t.startswith(("sửa note", "sua note")):
        try:
            parts = text.split()
            idx = int(parts[2])
            new_text = text.split(":", 1)[1].strip()
            return edit_note_in_sheet(idx, new_text)
        except Exception:
            return "Cú pháp đúng: sửa note 2: nội dung mới"

    # Xóa note
    if t.startswith(("xóa note", "xoá note", "xoa note")):
        try:
            idx = int([w for w in t.split() if w.isdigit()][0])
            return delete_note_in_sheet(idx)
        except Exception:
            return "Cú pháp đúng: xóa note 3"

    # Tìm trong Notes_Nha
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

    # Tìm trong User_Notes
    notes_user = get_notes_from_user()
    found_user = search_in_user_notes(t, notes_user)
    if found_user:
        reply = "🗂 *Thông tin từ ghi chú cá nhân:*\n\n"
        for item in found_user[:3]:
            reply += f"• {item.get('text', '')}\n"
        return reply.strip()

    return ask_llm(text)


# ================= FACEBOOK CONNECTOR =================

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


# ================= WEBHOOK =================

@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Sai verify token", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json() or {}
    print("\n🟢 DATA FACEBOOK GỬI VỀ:", data, "\n")

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
