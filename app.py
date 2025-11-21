import os
import threading
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

CHAT_MODEL = "gpt-4o-mini"
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
TEMPERATURE = 0.25
MAX_TOKENS = 200

# URL Apps Script dùng cho cả User_Notes và Notes_Nha
API_SHEET_URL = "https://script.google.com/macros/s/AKfycbzDElsgRSFc-JMWGSbDqvKqP0xwhWH3VQBXBNMktkhtPPXR5EgzI65iW9vvtiX6h1Tj/exec"

PAGE_TOKEN_MAP = {
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", "")
}

app = Flask(__name__)

try:
    client = OpenAI(api_key=OPENAI_KEY)
except:
    client = None


# =====================================
# 📘 GOOGLE SHEET FUNCTIONS
# =====================================
def get_notes_from_sheet(sheet_name):
    try:
        r = requests.post(API_SHEET_URL, params={"action": "get", "sheet": sheet_name})
        return r.json().get("notes", [])
    except:
        return []


def save_note_to_sheet(text, image_url=None):
    category = classify_note_category(text)
    payload = {
        "action": "add",
        "sheet": "User_Notes",
        "text": text,
        "category": category,
        "keywords": ", ".join([w.lower() for w in text.split() if len(w) >= 4]),
        "image_url": image_url or ""
    }
    requests.post(API_SHEET_URL, params=payload)
    return "Đã lưu ghi chú."


def edit_note_in_sheet(index, new_text):
    category = classify_note_category(new_text)
    payload = {
        "action": "edit",
        "sheet": "User_Notes",
        "index": str(index),
        "text": new_text,
        "category": category,
        "keywords": ", ".join([w.lower() for w in new_text.split() if len(w) >= 4]),
    }
    requests.post(API_SHEET_URL, params=payload)
    return f"Đã sửa note {index}."


def delete_note_in_sheet(index):
    payload = {"action": "delete", "sheet": "User_Notes", "index": str(index)}
    requests.post(API_SHEET_URL, params=payload)
    return f"Đã xóa note {index}."


# =====================================
# 🧠 AI CLASSIFY CATEGORY
# =====================================
def classify_note_category(text):
    n = text.lower()
    if any(k in n for k in ["giấy phép", "pháp lý", "xin phép"]): return "Giấy phép"
    if any(k in n for k in ["thiết kế", "phối cảnh", "cửa", "cad", "bản vẽ"]): return "Thiết kế"
    if any(k in n for k in ["móng", "thép", "cột", "dầm", "ép", "đổ", "d16", "d14"]): return "Thi công"
    if any(k in n for k in ["cửa", "sơn", "lát", "thiết bị", "nội thất", "gạch"]): return "Hoàn thiện"
    if any(k in n for k in ["bàn giao", "nghiệm thu"]): return "Bàn giao"
    if any(k in n for k in ["hoàn công", "sổ đỏ"]): return "Hoàn công"
    return "Chung"


# =====================================
# 🧠 AI FALLBACK
# =====================================
def ask_llm(text):
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": "Bạn là trợ lý xây nhà thực tế, rõ ràng, không dài dòng."},
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, tôi chưa rõ."


# =====================================
# 🤖 SMART REPLY ENGINE (CHÍNH)
# =====================================
def get_smart_reply(text, image_url=None):
    t = text.lower().strip()

    # 🟢 Ghi chú
    if t.startswith(("note:", "ghi nhớ:", "thêm:", "lưu:")):
        pure = text.split(":", 1)[1].strip()
        return save_note_to_sheet(pure, image_url=image_url)

    # 🟡 Sửa note
    if t.startswith("sửa note"):
        try:
            parts = text.split(":", 1)
            idx = int(parts[0].split()[2])
            return edit_note_in_sheet(idx, parts[1].strip())
        except:
            return "Cú pháp sửa: sửa note 2: nội dung mới"

    # 🔴 Xóa note
    if t.startswith(("xóa note", "xoá note")):
        try:
            idx = int([w for w in t.split() if w.isdigit()][0])
            return delete_note_in_sheet(idx)
        except:
            return "Cú pháp xóa: xóa note 3"

    # 📘 Xem toàn bộ note
    if t in ["xem note", "xem ghi chú", "ghi chú", "notes", "xem tất cả note"]:
        notes = get_notes_from_sheet("User_Notes")
        if not notes:
            return "Chưa có ghi chú nào."
        reply = "📘 Ghi chú đã lưu:\n\n"
        for i, n in enumerate(notes, 1):
            reply += f"{i}. ({n['category']}) {n['text']}\n"
        return reply

    # 🔍 Tra trong User_Notes trước
    notes_user = get_notes_from_sheet("User_Notes")
    best = None
    best_hits = 0
    for item in notes_user:
        kws = (item.get("keywords") or "").lower().split(",")
        hits = sum(1 for kw in kws if kw.strip() and kw.strip() in t)
        if hits > best_hits:
            best_hits = hits
            best = item
    if best_hits > 0:
        return f"📌Ghi chú đã lưu:\n{best['text']}"

    # 📚 Tra Notes_Nha
    notes_nha = get_notes_from_sheet("Notes_Nha")
    best = None
    best_hits = 0
    for item in notes_nha:
        kws = (item.get("keywords") or "").lower().split(",")
        hits = sum(1 for kw in kws if kw.strip() and kw.strip() in t)
        if hits > best_hits:
            best_hits = hits
            best = item
    if best_hits > 0:
        return best["text"]

    return ask_llm(text)


# =====================================
# 📡 FACEBOOK CONNECTOR
# =====================================
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
                reply = get_smart_reply(text, image_url=image_url)
                threading.Thread(target=send_text, args=(page_id, psid, reply)).start()
    return "OK", 200


@app.route("/health")
def health():
    return jsonify(status="running")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
