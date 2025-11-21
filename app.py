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

# 🔹 2 API tách riêng đúng như bạn yêu cầu
API_USER_NOTES = "https://script.google.com/macros/s/AKfycbzDElsgRSFc-JMWGSbDqvKqP0xwhWH3VQBXBNMktkhtPPXR5EgzI65iW9vvtiX6h1Tj/exec"
API_NOTES_NHA  = "https://script.google.com/macros/s/AKfycbxr2MCXn2OsZF8lZm5BfFARm4kBeGKZeSmtzPa_tydCdmJjzPwbzuE3CEkF5jYOFeFNKA/exec"

PAGE_TOKEN_MAP = {
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", "")
}

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None


# ================= GOOGLE SHEET HANDLERS =================
def get_notes_from_user():
    try:
        r = requests.post(API_USER_NOTES, params={"action": "get", "sheet": "User_Notes"})
        return r.json().get("notes", [])
    except:
        return []


def get_notes_from_nha():
    try:
        r = requests.post(API_NOTES_NHA, params={"action": "get", "sheet": "Notes_Nha"})
        return r.json().get("notes", [])
    except:
        return []


def save_note_to_sheet(text, image_url=None):
    payload = {
        "action": "add",
        "sheet": "User_Notes",
        "text": text,
        "category": classify_note_category(text),
        "keywords": ", ".join([w.lower() for w in text.split() if len(w) >= 4]),
        "image_url": image_url or ""
    }
    requests.post(API_USER_NOTES, params=payload)
    return "Đã lưu ghi chú."


def edit_note_in_sheet(index, new_text):
    payload = {
        "action": "edit",
        "sheet": "User_Notes",
        "index": str(index),
        "text": new_text,
        "category": classify_note_category(new_text),
        "keywords": ", ".join([w.lower() for w in new_text.split() if len(w) >= 4]),
    }
    requests.post(API_USER_NOTES, params=payload)
    return f"Đã sửa note {index}."


def delete_note_in_sheet(index):
    payload = {"action": "delete", "sheet": "User_Notes", "index": str(index)}
    requests.post(API_USER_NOTES, params=payload)
    return f"Đã xóa note {index}."


# ================= AI CATEGORY =================
def classify_note_category(text):
    n = text.lower()
    if any(k in n for k in ["giấy phép", "pháp lý", "xin phép"]): return "Giấy phép"
    if any(k in n for k in ["thiết kế", "phối cảnh", "cửa", "cad", "bản vẽ"]): return "Thiết kế"
    if any(k in n for k in ["móng", "thép", "cột", "d16", "d14", "dầm", "ép", "đổ"]): return "Thi công"
    if any(k in n for k in ["cửa", "sơn", "lát", "thiết bị", "nội thất", "gạch"]): return "Hoàn thiện"
    if any(k in n for k in ["bàn giao", "nghiệm thu"]): return "Bàn giao"
    if any(k in n for k in ["hoàn công", "sổ đỏ"]): return "Hoàn công"
    return "Chung"


# ================= AI FALLBACK =================
def ask_llm(text):
    if not client:
        return "AI chưa sẵn sàng."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": "Bạn là trợ lý xây nhà, trả lời rõ ràng, thực tế, ngắn gọn."},
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, tôi chưa rõ."


# ================= SMART REPLY =================
def get_smart_reply(text, image_url=None):
    t = text.lower().strip()

    # 🟢 Lưu ghi chú
    if t.startswith(("note:", "ghi nhớ:", "thêm:", "lưu:")):
        pure = text.split(":", 1)[1].strip()
        return save_note_to_sheet(pure, image_url)

    # ✏️ Sửa ghi chú
    if t.startswith("sửa note"):
        try:
            idx = int(text.split()[2])
            new_text = text.split(":", 1)[1].strip()
            return edit_note_in_sheet(idx, new_text)
        except:
            return "Cú pháp đúng: sửa note 2: nội dung mới"

    # ❌ Xóa ghi chú
    if t.startswith(("xóa note", "xoá note")):
        try:
            idx = int([w for w in t.split() if w.isdigit()][0])
            return delete_note_in_sheet(idx)
        except:
            return "Cú pháp đúng: xóa note 3"

    # 📘 Hiển thị toàn bộ ghi chú
    if t in ["xem note", "xem ghi chú", "ghi chú", "notes", "xem tất cả note"]:
        notes = get_notes_from_user()
        if not notes:
            return "Chưa có ghi chú nào."
        reply = "📘 Ghi chú đã lưu:\n\n"
        for i, n in enumerate(notes, 1):
            reply += f"{i}. ({n['category']}) {n['text']}\n"
        return reply

    # 🔍 Tra ghi chú cá nhân (ưu tiên)
    notes_user = get_notes_from_user()
    for item in notes_user:
        if item["text"] and any(kw in t for kw in item.get("keywords", "").split(",")):
            return f"📌Ghi chú đã lưu:\n{item['text']}"

    # 📚 Tra kiến thức chuẩn từ Notes_Nha
    notes_nha = get_notes_from_nha()
    for item in notes_nha:
        if item["text"] and any(kw in t for kw in item.get("keywords", "").split(",")):
            return item["text"]

    # 🤖 Cuối cùng: hỏi AI
    return ask_llm(text)


# ================= FACEBOOK CONNECTOR =================
def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        return
    requests.post(
        f"https://graph.facebook.com/v19.0/me/messages?access_token={token}",
        json={"recipient": {"id": psid}, "message": {"text": text}}
    )


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
            image_url = None

            # 📎 Nếu có ảnh
            for att in msg.get("attachments") or []:
                if att.get("type") == "image":
                    image_url = att.get("payload", {}).get("url")
                    break

            if psid and text:
                reply = get_smart_reply(text, image_url)
                threading.Thread(target=send_text, args=(page_id, psid, reply)).start()
    return "OK", 200


@app.route("/health")
def health():
    return jsonify(status="running")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
