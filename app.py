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

# 🔹 2 API tách riêng
API_USER_NOTES = "https://script.google.com/macros/s/AKfycbzQ8iI4FPilXsfiO-KVVk3kifaYwJkwqUGccAZZBRcm64WGkI4NIsjYyGWVao1_J-s/exec"
API_NOTES_NHA  = "https://script.google.com/macros/s/AKfycbwZvzjkGbbgY8OT3jtaSF5QUIBUd2Yjkpn6O9irz2Bf6uuBiZ1IJUU1F7YXnIlSdVyo4w/exec"

# 🔹 2 page token (mỗi page 1 token)
PAGE_TOKEN_MAP = {
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", ""),  # Page xây nhà
    "847842948414951": os.getenv("PAGE_TOKEN_CTT", ""),  
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),
}

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None


# ================= GOOGLE SHEET HANDLERS =================

def get_notes_from_user():
    """Lấy ghi chú từ sheet User_Notes."""
    try:
        r = requests.get(API_USER_NOTES, params={
            "action": "get",
            "sheet": "User_Notes"
        })
        data = r.json()
        return data.get("notes", [])
    except Exception as e:
        print("Lỗi get_notes_from_user:", e)
        return []


def get_notes_from_nha():
    """Lấy ghi chú chuẩn từ sheet Notes_Nha."""
    try:
        r = requests.get(API_NOTES_NHA, params={
            "action": "get",
            "sheet": "Notes_Nha"
        })
        data = r.json()
        return data.get("notes", [])
    except Exception as e:
        print("Lỗi get_notes_from_nha:", e)
        return []


def save_note_to_sheet(text, image_url=None):
    """Thêm ghi chú mới vào User_Notes."""
    payload = {
        "action": "add",
        "sheet": "User_Notes",
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
    """Sửa nội dung ghi chú tại index."""
    payload = {
        "action": "edit",
        "sheet": "User_Notes",
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
    """Xóa ghi chú tại index."""
    payload = {
        "action": "delete",
        "sheet": "User_Notes",
        "index": str(index)
    }
    try:
        requests.post(API_USER_NOTES, data=payload)
        return f"Đã xóa note {index}."
    except Exception as e:
        print("Lỗi delete_note_in_sheet:", e)
        return "Lỗi khi xóa ghi chú."


# ================= AI CATEGORY =================

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


# ================= AI FALLBACK =================

def ask_llm(text):
    if not client:
        return "AI chưa sẵn sàng (chưa có OPENAI_API_KEY)."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Bạn là trợ lý xây nhà, trả lời rõ ràng, thực tế, ngắn gọn."
                },
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("Lỗi ask_llm:", e)
        return "Xin lỗi, tôi chưa rõ."


# ================= SMART REPLY =================

def get_smart_reply(text, image_url=None):
    t = text.lower().strip()

    # 🟢 Lưu ghi chú: note: / ghi nhớ: / thêm: / lưu:
    if t.startswith(("note:", "ghi nhớ:", "ghi nho:", "thêm:", "them:", "lưu:", "luu:")):
        pure = text.split(":", 1)[1].strip()
        return save_note_to_sheet(pure, image_url)

    # ✏️ Sửa ghi chú: "sửa note 2: nội dung mới"
    if t.startswith("sửa note") or t.startswith("sua note"):
        try:
            # vd: "sửa note 2: đặt lại cửa 2x3m"
            parts = text.split()
            idx = int(parts[2])
            new_text = text.split(":", 1)[1].strip()
            return edit_note_in_sheet(idx, new_text)
        except Exception:
            return "Cú pháp đúng: sửa note 2: nội dung mới"

    # ❌ Xóa ghi chú: "xóa note 3"
    if t.startswith(("xóa note", "xoá note", "xoa note")):
        try:
            idx = int([w for w in t.split() if w.isdigit()][0])
            return delete_note_in_sheet(idx)
        except Exception:
            return "Cú pháp đúng: xóa note 3"

    # 📘 Hiển thị toàn bộ ghi chú
    if t in ["xem note", "xem ghi chú", "ghi chú", "ghi chu", "notes", "xem tất cả note", "xem tat ca note"]:
        notes = get_notes_from_user()
        if not notes:
            return "Chưa có ghi chú nào."
        reply = "📘 Ghi chú đã lưu:\n\n"
        for i, n in enumerate(notes, 1):
            reply += f"{i}. ({n.get('category', 'Chung')}) {n.get('text', '')}\n"
        return reply

    # 🔍 Tra ghi chú cá nhân (ưu tiên)
    notes_user = get_notes_from_user()
    t_words = [w.strip(".,;:!?").lower() for w in t.split()]
    for item in notes_user:
        text_item = item.get("text", "")
        kw_str = item.get("keywords", "")
        kws = [k.strip().lower() for k in kw_str.split(",") if k.strip()]
        if text_item and any(k in t for k in kws):
            return f"📌 Ghi chú đã lưu:\n{text_item}"

    # 📚 Tra kiến thức chuẩn từ Notes_Nha
    notes_nha = get_notes_from_nha()
    for item in notes_nha:
        text_item = item.get("text", "")
        kw_str = item.get("keywords", "")
        kws = [k.strip().lower() for k in kw_str.split(",") if k.strip()]
        if text_item and any(k in t for k in kws):
            return text_item

    # 🤖 Cuối cùng: hỏi AI
    return ask_llm(text)


# ================= FACEBOOK CONNECTOR =================

def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        print("Không tìm thấy token cho page_id:", page_id)
        return

    try:
        print(f"💬 Gửi tới {psid} (page {page_id}): {text}")
        requests.post(
            f"https://graph.facebook.com/v19.0/me/messages",
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
            image_url = None

            # 📎 Nếu có ảnh kèm theo
            for att in msg.get("attachments") or []:
                if att.get("type") == "image":
                    image_url = att.get("payload", {}).get("url")
                    break

            if psid and text:
                reply = get_smart_reply(text, image_url)
                # Gửi reply ở thread riêng để trả 200 OK cho FB nhanh
                threading.Thread(target=send_text, args=(page_id, psid, reply)).start()

    return "OK", 200


@app.route("/health")
def health():
    return jsonify(status="running")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"Server chạy trên port {port}")
    app.run(host="0.0.0.0", port=port)




