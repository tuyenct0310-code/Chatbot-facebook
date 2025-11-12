import os, json, random, requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

PAGE_TOKEN   = os.environ["PAGE_ACCESS_TOKEN"]
VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# ===================================
#  NẠP TẤT CẢ FILE JSON TRONG /data
# ===================================
def load_all_json():
    data = {}
    data_folder = "data"
    if not os.path.exists(data_folder):
        return data
    for filename in os.listdir(data_folder):
        if filename.endswith(".json"):
            path = os.path.join(data_folder, filename)
            with open(path, "r", encoding="utf-8") as f:
                try:
                    content = json.load(f)
                    data[filename.replace(".json", "")] = content
                except Exception as e:
                    print("❌ Lỗi đọc file", filename, ":", e)
    print("✅ Đã nạp:", list(data.keys()))
    return data

DATABASE = load_all_json()

# ===================================
#  XỬ LÝ TIN NHẮN NGƯỜI DÙNG
# ===================================
def find_reply(user_text):
    text = user_text.lower()

    # --- Ưu tiên Chatbot Ctt ---
    if any(k in text for k in ["chatbot", "ctt", "trợ lý ảo", "bán chatbot", "dùng thử", "cài chatbot"]):
        data = DATABASE.get("quangcao_chatbot_ctt", {})
        if not data:
            return None
        # Dò từng nhóm
        for key, responses in data.items():
            if any(k in text for k in key.split("_")):
                return random.choice(responses)
        # Nếu không khớp nhóm → trả lời chào hoặc lợi ích
        return random.choice(data.get("chào", data.get("lợi_ích", ["Chatbot Ctt giúp shop bạn trả lời khách 24/7!"])))

    # --- Ưu tiên Quán Ốc ---
    if any(k in text for k in ["ốc", "ngon", "hàu", "lẩu", "ngao", "hương", "ốc đồng", "nhậu", "quán", "bàn", "tối", "món", "mon", "phục vụ"]):
        data = DATABASE.get("oc_ngon_18", {})
        if not data:
            return None

        # Kiểm tra món trong menu
        for category, items in data.get("Danh mục món", {}).items():
            if isinstance(items, dict):
                for mon, gia in items.items():
                    if mon.lower() in text:
                        return f"👉 {mon} ({category}) có giá {gia} nha!"

        # Nếu không phải món → xem quảng cáo
        qc = data.get("Quảng cáo quán", {})
        if any(k in text for k in ["chào", "hello", "xin chào"]):
            return random.choice(qc.get("chào", []))
        if any(k in text for k in ["giới thiệu", "có gì ngon", "quán này", "đặc biệt", "món ngon"]):
            return random.choice(qc.get("giới_thiệu", []))
        if any(k in text for k in ["khuyến mãi", "giảm giá", "ưu đãi"]):
            return random.choice(qc.get("khuyến_mãi", []))
        if any(k in text for k in ["địa chỉ", "ở đâu", "liên hệ", "số điện thoại", "map"]):
            return random.choice(qc.get("liên_hệ", []))
        if any(k in text for k in ["cảm ơn", "bye", "tạm biệt", "hẹn gặp"]):
            return random.choice(qc.get("kết_thúc", []))
        return random.choice(data.get("Quảng cáo quán", {}).get("giới_thiệu", []))

    # --- Không thuộc dữ liệu có sẵn ---
    return None

# ===================================
#  GỌI OPENAI KHI KHÔNG CÓ TRONG DỮ LIỆU
# ===================================
def call_openai(user_text):
    local_reply = find_reply(user_text)
    if local_reply:
        return local_reply

    # fallback dùng OpenAI nếu không tìm thấy trong JSON
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Bạn là Chatbot Ctt – nói chuyện vui vẻ, tự nhiên như người thật. Trả lời ngắn gọn, có cảm xúc, thêm emoji phù hợp."}

            {"role": "user", "content": user_text}
        ],
        temperature=0.4,
    )
    return resp.choices[0].message.content.strip()

# ===================================
#  GỬI TIN NHẮN VỀ FACEBOOK
# ===================================
def send_text(psid, text):
    requests.post(FB_SEND_URL, json={
        "recipient": {"id": psid},
        "message": {"text": text}
    }, timeout=15)

# ===================================
#  WEBHOOK FACEBOOK
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
            if psid and msg:
                try:
                    reply = call_openai(msg)
                except Exception as e:
                    reply = "Xin lỗi, hệ thống đang bận. Vui lòng thử lại sau."
                    print("OpenAI error:", e)
                send_text(psid, reply)
    return "EVENT_RECEIVED"

@app.route("/health")
def health():
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))


