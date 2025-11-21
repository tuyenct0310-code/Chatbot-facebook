import os
import json
import time
import threading
import requests
from pathlib import Path
from flask import Flask, request, jsonify
from openai import OpenAI

# =====================
# CONFIG
# =====================
CHAT_MODEL = "gpt-4o-mini"
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
TEMPERATURE = 0.25
MAX_TOKENS = 200

API_SHEET_URL = "https://script.google.com/macros/s/AKfycbxr2MCXn2OsZF8lZm5BfFARm4kBeGKZeSmtzPa_tydCdmJjzPwbzuE3CEkF5jYOFeFNKA/exec"

PAGE_TOKEN_MAP = {
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", "")
}

app = Flask(__name__)

try:
    client = OpenAI(api_key=OPENAI_KEY)
except:
    client = None


# =========================
# SHEET FUNCTIONS
# =========================
def get_notes_from_sheet(sheet_name):
    try:
        url = f"{API_SHEET_URL}?sheet={sheet_name}"
        r = requests.get(url)
        return r.json().get("notes", [])
    except:
        return []


def save_note_to_sheet(text, image_url=None):
    category = classify_note_category(text)
    payload = {
        "text": text,
        "category": category,
        "keywords": ", ".join([w.lower() for w in text.split() if len(w) >= 4]),
        "image_url": image_url or ""
    }
    try:
        requests.post(API_SHEET_URL, params=payload)
    except:
        pass
    return "Đã lưu ghi chú vào Google Sheet."


def edit_note_in_sheet(index, new_text, image_url=None):
    category = classify_note_category(new_text)
    payload = {
        "action": "edit",
        "index": str(index),
        "text": new_text,
        "category": category,
        "keywords": ", ".join([w.lower() for w in new_text.split() if len(w) >= 4]),
        "image_url": image_url or "",
        "sheet": "User_Notes"
    }
    try:
        r = requests.post(API_SHEET_URL, params=payload)
        data = {}
        try:
            data = r.json()
        except:
            pass
        if data.get("error"):
            return f"Lỗi sửa note: {data.get('error')}"
        return f"Đã sửa note {index}."
    except:
        return "Không kết nối được Google Sheet khi sửa note."


def delete_note_in_sheet(index):
    payload = {
        "action": "delete",
        "index": str(index),
        "sheet": "User_Notes"
    }
    try:
        r = requests.post(API_SHEET_URL, params=payload)
        data = {}
        try:
            data = r.json()
        except:
            pass
        if data.get("error"):
            return f"Lỗi xóa note: {data.get('error')}"
        return f"Đã xóa note {index}."
    except:
        return "Không kết nối được Google Sheet khi xóa note."


# =========================
# NOTE AI SMART CLASSIFY
# =========================
def classify_note_category(text):
    n = text.lower()
    if any(k in n for k in ["giấy phép", "pháp lý", "xin phép"]): return "Giấy phép"
    if any(k in n for k in ["thiết kế", "bản vẽ", "phối cảnh", "cửa", "cad"]): return "Thiết kế"
    if any(k in n for k in ["móng", "thép", "cột", "dầm", "ép", "đổ"]): return "Thi công"
    if any(k in n for k in ["cửa", "sơn", "lát", "thiết bị", "nội thất"]): return "Hoàn thiện"
    if any(k in n for k in ["bàn giao", "kiểm tra", "nghiệm thu"]): return "Bàn giao"
    if any(k in n for k in ["hoàn công", "sổ đỏ", "hồ sơ"]): return "Hoàn công"
    return "Chung"


# =========================
# AI FALLBACK
# =========================
def ask_llm(text):
    if not client:
        return "Hệ thống AI chưa sẵn sàng."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": "Bạn là trợ lý xây nhà thực tế, ngắn gọn, rõ ràng."},
                {"role": "user", "content": text}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, tôi chưa rõ thông tin."


# =========================
# SMART REPLY
# =========================
def get_smart_reply(text, image_url=None):
    t = text.lower().strip()

    # 📌 Ghi chú mới (có thể kèm ảnh)
    if t.startswith(("note:", "ghi nhớ:", "thêm:", "lưu:")):
        pure = text.split(":", 1)[1].strip()
        return save_note_to_sheet(pure, image_url=image_url)

    # 📝 Sửa note: "sửa note 2: nội dung mới"
    if t.startswith("sửa note"):
        try:
            parts = text.split(":", 1)
            left = parts[0].strip()           # "sửa note 2"
            new_text = parts[1].strip()       # "nội dung mới"
            idx_str = left.split()[2]         # "2"
            idx = int(idx_str)
            return edit_note_in_sheet(idx, new_text)
        except Exception:
            return "Cú pháp sửa: Sửa note 2: nội dung mới"

    # ❌ Xóa note: "xóa note 3"
    if t.startswith(("xóa note", "xoá note")):
        try:
            # tìm số đầu tiên trong câu
            idx = None
            for token in t.split():
                if token.isdigit():
                    idx = int(token)
                    break
            if not idx:
                return "Cú pháp xóa: Xóa note 3"
            return delete_note_in_sheet(idx)
        except Exception:
            return "Cú pháp xóa: Xóa note 3"

    # 📘 Xem toàn bộ ghi chú
    if t in ["xem note", "xem ghi chú", "note", "ghi chú", "xem tất cả note"]:
        notes = get_notes_from_sheet("User_Notes")
        if not notes:
            return "Chưa có ghi chú nào."
        reply = "📘 Các ghi chú đã lưu:\n\n"
        for i, n in enumerate(notes, 1):
            img_mark = " [Có ảnh]" if n.get("image_url") else ""
            reply += f"{i}. ({n['category']}) {n['text']}{img_mark}\n"
        return reply

    # 🎯 Xem note theo category
    categories = {
        "thi công": "Thi công",
        "thiết kế": "Thiết kế",
        "giấy phép": "Giấy phép",
        "hoàn thiện": "Hoàn thiện",
        "bàn giao": "Bàn giao",
        "hoàn công": "Hoàn công"
    }
    for k, v in categories.items():
        if t.startswith(f"xem note {k}"):
            notes = get_notes_from_sheet("User_Notes")
            filtered = [n for n in notes if n["category"].lower() == v.lower()]
            if not filtered:
                return f"Chưa có ghi chú mục {v}."
            reply = f"📘 Ghi chú mục {v}:\n\n"
            for i, n in enumerate(filtered, 1):
                img_mark = " [Có ảnh]" if n.get("image_url") else ""
                reply += f"{i}. {n['text']}{img_mark}\n"
            return reply

    # 🔎 Tìm trong Notes_Nha (kiến thức kỹ thuật)
    notes_nha = get_notes_from_sheet("Notes_Nha")
    t_low = t.lower()
    best = None
    best_hits = 0
    for item in notes_nha:
        kws = (item.get("keywords") or "").lower().split(",")
        hits = sum(1 for kw in kws if kw.strip() and kw.strip() in t_low)
        if hits > best_hits:
            best_hits = hits
            best = item
    if best and best_hits > 0:
        return best["text"]

    # 🔥 Không có trong Sheet → hỏi AI
    return ask_llm(text)


# =========================
# FACEBOOK
# =========================
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

            # lấy ảnh nếu có gửi kèm
            atts = msg.get("attachments") or []
            for att in atts:
                if att.get("type") == "image":
                    payload = att.get("payload") or {}
                    image_url = payload.get("url")
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
