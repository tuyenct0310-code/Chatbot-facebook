import os, json, requests, random
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

PAGE_TOKEN   = os.environ["PAGE_ACCESS_TOKEN"]
VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# ===================================
# TỰ ĐỘNG NẠP TOÀN BỘ FILE JSON TRONG /data
# ===================================
def load_all_json():
    data_folder = "data"
    all_data = {}
    if not os.path.exists(data_folder):
        return all_data
    for filename in os.listdir(data_folder):
        if filename.endswith(".json"):
            path = os.path.join(data_folder, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    all_data[filename.replace(".json", "")] = content
            except Exception as e:
                print(f"Lỗi đọc {filename}:", e)
    return all_data

# Nạp toàn bộ dữ liệu JSON
DATABASE = load_all_json()
print("✅ Đã nạp dữ liệu:", list(DATABASE.keys()))


# ===================================
# HÀM TÌM TRONG TOÀN BỘ CƠ SỞ DỮ LIỆU
# ===================================
def find_in_database(user_text):
    text = user_text.lower()
    for name, info in DATABASE.items():

        # --- Nếu là chatbot Ctt ---
        if "chatbot" in name or "ctt" in name:
            if any(k in text for k in ["chatbot", "bán chatbot", "trợ lý ảo", "dùng thử", "cài đặt"]):
                # Tìm nhóm phù hợp
                for group, items in info.items():
                    if any(x in text for x in [group.replace("_", " "), group]):
                        return random.choice(items)
                # Nếu không khớp cụ thể → trả lời ngẫu nhiên nhóm chào hoặc lợi_ích
                return random.choice(info.get("chào", info.get("lợi_ích", ["Đây là Chatbot Ctt — trợ lý AI miễn phí 7 ngày!"])))

        # --- Nếu là quán ăn (ví dụ Ốc Ngon 18) ---
        if "Tên quán" in info:
            # Tìm sản phẩm
            for danh_muc, items in info.get("Danh mục món", {}).items():
                if isinstance(items, dict):
                    for mon, gia in items.items():
                        if mon.lower() in text:
                            return f"👉 {mon} ({danh_muc}) có giá {gia} nha!"
            # Tìm quảng cáo
            qc = info.get("Quảng cáo quán", {})
            if any(x in text for x in ["chào", "hello", "xin chào"]):
                return random.choice(qc.get("chào", []))
            if any(x in text for x in ["giới thiệu", "có gì ngon", "quán này", "đặc biệt", "món ngon"]):
                return random.choice(qc.get("giới_thiệu", []))
            if any(x in text for x in ["khuyến mãi", "giảm giá", "ưu đãi"]):
                return random.choice(qc.get("khuyến_mãi", []))
            if any(x in text for x in ["địa chỉ", "ở đâu", "map", "liên hệ", "số điện thoại"]):
                return random.choice(qc.get("liên_hệ", []))
            if any(x in text for x in ["cảm ơn", "hẹn gặp", "bye"]):
                return random.choice(qc.get("kết_thúc", []))

    return None


# ===================================
# GỌI OPENAI HOẶC TRA TỪ JSON
# ===================================
def call_openai(user_text):
    reply = find_in_database(user_text)
    if reply:
        return reply

    # fallback nếu không có dữ liệu trong JSON
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Bạn là chatbot thân thiện, hỗ trợ khách hàng và giới thiệu sản phẩm."},
            {"role": "user", "content": user_text}
        ],
        temperature=0.5,
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

