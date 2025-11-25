import os
import threading
import requests
import re
from flask import Flask, request, jsonify
from openai import OpenAI

# ===================== CONFIG =====================
CHAT_MODEL = "gpt-4o-mini"
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
TEMPERATURE = 0.25
MAX_TOKENS = 200

# 🔹 API của User Notes, Notes_Nha, và Quần Áo
API_USER_NOTES = "https://script.google.com/macros/s/API_USER_NOTES_EXEC/exec"
API_NOTES_NHA  = "https://script.google.com/macros/s/API_NOTES_NHA_EXEC/exec"
API_FASHION    = "https://script.google.com/macros/s/API_FASHION_EXEC/exec"

# 🔹 3 Page của bạn
PAGE_TOKEN_MAP = {
    "813440285194304": os.getenv("PAGE_TOKEN_NHA", ""),  
    "847842948414951": os.getenv("PAGE_TOKEN_CTT", ""),  
    "895305580330861": os.getenv("PAGE_TOKEN_A", ""),  # Quần áo
}

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# Giỏ hàng trong RAM
CARTS = {}

# ================= GOOGLE SHEET HANDLERS =================

def get_notes_from_user():
    try:
        r = requests.get(API_USER_NOTES, params={"action": "get", "sheet": "User_Notes"})
        return r.json().get("notes", [])
    except:
        return []

def get_notes_from_nha():
    try:
        r = requests.get(API_NOTES_NHA, params={"action": "get", "sheet": "Notes_Nha"})
        return r.json().get("notes", [])
    except:
        return []

def get_fashion_items():
    try:
        r = requests.get(API_FASHION, params={"action": "get", "sheet": "QuanAo"})
        return r.json().get("items", [])
    except:
        return []

def save_order_to_sheet(psid, customer_info, cart_items, total_amount):
    payload = {
        "action": "order",
        "sheet": "Orders",
        "psid": psid,
        "customer_info": customer_info,
        "cart": "\n".join(cart_items),
        "total": str(total_amount)
    }
    try:
        requests.get(API_FASHION, params=payload)
        return "Đơn hàng đã được ghi nhận, sẽ có người liên hệ bạn sớm."
    except:
        return "Lỗi khi lưu đơn hàng."

# ================= AI FALLBACK =================
def ask_llm(text):
    if not client:
        return "AI chưa sẵn sàng."
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "system", "content": "Trả lời ngắn, rõ ràng."},
                      {"role": "user", "content": text}],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Xin lỗi, tôi chưa rõ."

# ================= PAGE QUẦN ÁO HANDLER =================
def handle_fashion_page(text, t, psid):
    global CARTS
    items = get_fashion_items()
    cart = CARTS.get(psid, [])

    # Xem sản phẩm
    if t in ["xem sp", "xem sản phẩm", "catalog"]:
        reply = "🛍 DANH SÁCH SẢN PHẨM:\n\n"
        for i, it in enumerate(items, 1):
            reply += f"{i}. {it['ten_sp']} - {it['gia']} - Size {it['size']}\n"
        return reply + "\nGõ: 'mua sp 1', 'mua sp 2 x2' để mua."

    # Thêm vào giỏ
    if "mua sp" in t or "thêm vào giỏ" in t:
        nums = [int(x) for x in t.split() if x.isdigit()]
        if not nums:
            return "Gõ: mua sp 2 hoặc mua sp 2 x3."
        idx = nums[0]
        qty = nums[1] if len(nums) > 1 else 1
        it = items[idx - 1]
        cart.append({"ten": it["ten_sp"], "gia": it["gia"], "size": it["size"], "qty": qty})
        CARTS[psid] = cart
        return f"Đã thêm vào giỏ: {it['ten_sp']} x{qty}"

    # Xem giỏ hàng
    if t in ["giỏ hàng", "xem giỏ"]:
        if not cart:
            return "Giỏ hàng đang trống."
        reply = "🧺 GIỎ HÀNG:\n\n"
        total = 0
        for c in cart:
            price = int(re.sub(r'\D','',c["gia"]))
            total += price * c["qty"]
            reply += f"{c['ten']} - {c['gia']} x{c['qty']}\n"
        return reply + f"\nTổng: {total:,}đ\nGõ 'đặt hàng: tên, sđt, địa chỉ' để chốt đơn."

    # Đặt hàng
    if t.startswith("đặt hàng"):
        if not cart:
            return "Giỏ hàng trống."
        info = text.split(":",1)[1].strip()
        lines, total = [], 0
        for c in cart:
            price = int(re.sub(r'\D','',c["gia"]))
            total += price * c["qty"]
            lines.append(f"{c['ten']} x{c['qty']} - {c['gia']}")
        CARTS[psid] = []  # Xóa giỏ sau khi đặt
        return save_order_to_sheet(psid, info, lines, total)

    # Nếu không khớp → AI trả lời
    return ask_llm(text)

# ================= PAGE NHÀ HANDLER =================
def handle_nha_page(text, t):
    notes_nha = get_notes_from_nha()

    # Tra vật tư
    for item in notes_nha:
        kws = item.get("keywords","").lower().split()
        if any(k in t for k in kws):
            return (f"📌 {item['hang_muc']}\n"
                    f"🔹 Chi tiết: {item['chi_tiet']}\n"
                    f"🏷 Thương hiệu: {item['thuong_hieu']}\n"
                    f"📏 Đơn vị: {item['don_vi']}")

    return ask_llm(text)

# ================= SMART REPLY =================
def get_smart_reply(text, image_url=None, page_id=None, psid=None):
    t = text.lower().strip()

    if page_id == "895305580330861":  
        return handle_fashion_page(text, t, psid)

    if page_id == "813440285194304":  
        return handle_nha_page(text, t)

    return ask_llm(text)

# ================= FACEBOOK CONNECTOR =================
def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        return
    requests.post(
        "https://graph.facebook.com/v19.0/me/messages",
        params={"access_token": token},
        json={"recipient": {"id": psid}, "message": {"text": text}}
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json() or {}
    for entry in data.get("entry", []):
        page_id = entry.get("id")
        for event in entry.get("messaging", []):
            psid = event.get("sender", {}).get("id")
            msg = event.get("message", {})
            text = msg.get("text")
            image_url = None
            if psid and text:
                reply = get_smart_reply(text, image_url, page_id, psid)
                threading.Thread(target=send_text, args=(page_id, psid, reply)).start()
    return "OK", 200


@app.route("/health")
def health():
    return jsonify(status="running")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
