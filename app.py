import os, json, requests, random
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

PAGE_TOKEN   = os.environ["PAGE_ACCESS_TOKEN"]
VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# ===================================
# TỰ ĐỘNG NẠP TẤT CẢ FILE JSON TRONG THƯ MỤC /data
# ===================================
def load_all_json():
    data_folder = "data"
    all_data = {}
    for filename in os.listdir(data_folder):
        if filename.endswith(".json"):
            path = os.path.join(data_folder, filename)
            with open(path, "r", encoding="utf-8") as f:
                try:
                    content = json.load(f)
                    all_data[filename.replace(".json", "")] = content
                except Exception as e:
                    print(f"Lỗi đọc {filename}:", e)
    return all_data

# Load tất cả file JSON
DATABASE = load_all_json()

# ===================================
# HÀM TÌM SẢN PHẨM / THÔNG TIN QUÁN
# ===================================
def find_product(user_text):
    text = user_text.lower()
    for shop_name, info in DATABASE.items():
        # Kiểm tra sản phẩm
        for name, price in info.get("Sản phẩm", {}).items():
            if name.lower() in text:
                return f"👉 {name} của {info.get('Tên quán')} có giá {price} nhé!"
        # Kiểm tra địa chỉ
        if any(x in text for x in ["địa chỉ", "ở đâu", "vị trí", "map"]):
            return f"📍 {info.get('Tên quán')} ở {info.get('Địa chỉ')}."
        # Kiểm tra số điện thoại
        if any(x in text for x in ["số điện thoại", "liên hệ", "đặt bàn", "gọi điện"]):
            phones = ", ".join(info.get("Số điện thoại", []))
            return f"📞 Liên hệ {info.get('Tên quán')}: {phones}"
    return None

# ===================================
# HÀM TRẢ LỜI NGƯỜI DÙNG
# ===================================
def call_openai(user_text):
    reply = find_product(user_text)
    if reply:
        return reply

    # fallback qua AI nếu không khớp
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Bạn là chatbot hỗ trợ khách hàng cho nhiều quán ăn, trả lời ngắn gọn, vui vẻ."},
            {"role": "user", "content": user_text}
        ],
        temperature=0.4,
    )
    return resp.choices[0].message.content.strip()

# ===================================
# GỬI TIN TRẢ LỜI VỀ MESSENGER
# ===================================
def send_text(psid, text):
    requests.post(FB_SEND_URL, json={
        "recipient": {"id": psid},
        "message": {"text": text}
    }, timeout=15)

# ===================================
# ROUTE FACEBOOK WEBHOOK
# ===================================
@app.route("/webhook", methods=["GET"])
def verify():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        return str(challenge)
    return "Sai verify token", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    for entry in data.get("entry", []):
        for evt in entry.get("messaging", []):
            psid = evt.get("sender", {}).get("id")
            msg = evt.get("message", {}).get("text")
            if not msg and "postback" in evt:
                msg = evt["postback"].get("payload") or evt["postback"].get("title")

            if psid and msg:
                try:
                    reply = call_openai(msg)
                except Exception as e:
                    reply = "Xin lỗi, hệ thống đang bận."
                    print("OpenAI error:", e)
                try:
                    send_text(psid, reply)
                except Exception as e:
                    print("Send error:", e)
    return "EVENT_RECEIVED"

@app.route("/health")
def health():
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
