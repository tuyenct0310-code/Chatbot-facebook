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

# 🔹 Chỉ còn 1 API duy nhất
API_NOTES = "https://script.google.com/macros/s/AKfycbyovjcqIwqP9oLqljcrhcZojussoPkD5uKD1SMciw5flrN2cMf2LgdUgM1bVIrCr0vO/exec"

# 🔹 Facebook Page tokens
PAGE_TOKEN_MAP = {
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", ""),  # Page Nhà
    "847842948414951": os.getenv("PAGE_TOKEN_CTT", ""),  # Page thời trang
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),    # Page khác
}
PAGE_ID_NHA = "813440285194304"

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None


# ================= GOOGLE SHEET =================

def get_notes(sheet_name):
    """Lấy dữ liệu từ Notes_Nha hoặc User_Notes"""
    try:
        r = requests.get(API_NOTES, params={"action": "get", "sheet": sheet_name})
        print(f"{sheet_name} raw:", r.text)
        return r.json().get("notes", [])
    except Exception as e:
        print(f"Lỗi get_notes({sheet_name}):", e)
        return []


# ================= CRUD USER NOTES =================

def classify_note_category(text):
    t = text.lower()
    if any(k in t for k in ["giấy phép", "pháp lý", "xin phép"]): return "Giấy phép"
    if any(k in t for k in ["thiết kế", "cửa", "cad", "bản vẽ"]): return "Thiết kế"
    if any(k in t for k in ["móng", "thép", "cột", "ép", "đổ"]): return "Thi công"
    if any(k in t for k in ["sơn", "lát", "thiết bị", "nội thất"]): return "Hoàn thiện"
    if any(k in t for k in ["bàn giao", "nghiệm thu"]): return "Bàn giao"
    return "Chung"


def save_note_to_sheet(text, image_url=None):
    payload = {
        "action": "add",
        "text": text,
        "category": classify_note_category(text),
        "keywords": ", ".join([w for w in text.lower().split() if len(w) >= 4]),
        "image_url": image_url or ""
    }
    try:
        requests.post(API_NOTES, data=payload)
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
        "keywords": ", ".join([w for w in new_text.lower().split() if len(w) >= 4])
    }
    try:
        requests.post(API_NOTES, data=payload)
        return f"Đã sửa note {index}."
    except Exception as e:
        print("Lỗi edit_note_in_sheet:", e)
        return "Lỗi khi sửa ghi chú."


def delete_note_in_sheet(index):
    payload = {"action": "delete", "index": str(index)}
    try:
        requests.post(API_NOTES, data=payload)
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
                 "content": "Bạn là trợ lý xây nhà, trả lời rõ ràng, gọn, thực tế."},
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return "Xin lỗi, tôi chưa rõ."


# ================= SEARCH HELPERS =================

def search_notes(query, notes, fields):
    query = query.lower()
    results = []
    for item in notes:
        for f in fields:
            if f in item and query in str(item[f]).lower():
                results.append(item)
                break
    return results


# ================= SMART REPLY =================

def get_smart_reply(text, image_url=None, page_id=None):
    t = text.lower().strip()

    # Nếu không phải Page Nhà → chỉ dùng AI
    if page_id != PAGE_ID_NHA:
        return ask_llm(text)

    # Xem ghi chú
    if t in ["xem note", "xem ghi chú", "notes"]:
        notes = get_notes("User_Notes")
        if not notes:
            return "Chưa có ghi chú nào."
        return "\n".join([
            f"{i+1}. ({n.get('category','')}) {n.get('text','')}"
            for i, n in enumerate(notes)
        ])

    # Lưu ghi chú
    if t.startswith(("note:", "ghi nhớ:", "thêm:", "lưu:")):
        pure = text.split(":", 1)[1].strip()
        return save_note_to_sheet(pure, image_url)

    # Sửa ghi chú
    if t.startswith("sửa note"):
        try:
            idx = int(t.split()[2])
            new_text = text.split(":", 1)[1].strip()
            return edit_note_in_sheet(idx, new_text)
        except:
            return "Cú pháp đúng: sửa note 2: nội dung mới"

    # Xóa ghi chú
    if t.startswith(("xóa note", "xoá note")):
        try:
            idx = int([x for x in t.split() if x.isdigit()][0])
            return delete_note_in_sheet(idx)
        except:
            return "Cú pháp đúng: xóa note 2"

    # ================= Tìm Notes_Nha (vật tư)
    notes_nha = get_notes("Notes_Nha")
    found_nha = search_notes(t, notes_nha,
                             ["hang_muc", "chi_tiet", "thuong_hieu"])
    if found_nha:
        reply = "📌 Thông tin vật tư:\n\n"
        for item in found_nha[:3]:
            reply += (
                f"📌 {item.get('hang_muc', '')}\n"
                f"🔹 Chi tiết: {item.get('chi_tiet','')}\n"
                f"🏷 Thương hiệu: {item.get('thuong_hieu','')}\n"
                f"📏 Đơn vị: {item.get('don_vi','')}\n"
                f"📝 Ghi chú: {item.get('ghi_chu','')}\n\n"
            )
        return reply.strip()

    # ================= Tìm ghi chú cá nhân
    notes_user = get_notes("User_Notes")
    found_user = search_notes(t, notes_user, ["text", "keywords"])
    if found_user:
        return "🗂 Ghi chú cá nhân:\n" + "\n".join(
            f"• {n.get('text','')}" for n in found_user[:3]
        )

    return ask_llm(text)


# ================= FACEBOOK CONNECTOR =================

def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
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
    app.run(host="0.0.0.0", port=port)
