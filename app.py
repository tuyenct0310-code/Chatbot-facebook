import os, json, random, requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# --- Lấy biến môi trường ---
PAGE_TOKEN   = os.environ.get("PAGE_ACCESS_TOKEN", "YOUR_PAGE_ACCESS_TOKEN_HERE")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "YOUR_VERIFY_TOKEN_HERE")
OPENAI_KEY   = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")

# --- Khởi tạo ---
client = OpenAI(api_key=OPENAI_KEY)
FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"


# ===================================
#  NẠP KNOWLEDGE BASE (CHỈ 1 FILE)
# ===================================
def load_knowledge_base(filename="data/kientruc_xyz.json"):
    """
    Nạp 1 file JSON duy nhất làm "não" cho bot.
    File này BẮT BUỘC phải nằm trong thư mục /data
    """
    if not os.path.exists(filename):
        print(f"❌ LỖI NGHIÊM TRỌNG: Không tìm thấy file knowledge base '{filename}'.")
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = json.load(f)
            print(f"✅ Đã nạp thành công knowledge base: {filename}")
            return content
    except Exception as e:
        print(f"❌ Lỗi đọc file {filename}: {e}")
        return None

# Nạp "não" cho bot khi khởi động
DATABASE = load_knowledge_base()


# ===================================
#  TÌM TRONG DỮ LIỆU JSON (Fast-path)
# ===================================
def find_in_json(user_text):
    """
    Tìm các câu trả lời nhanh (fast-path) để tiết kiệm API OpenAI.
    Chỉ xử lý các câu hỏi đơn giản, cố định.
    """
    text = user_text.lower()
    
    if not DATABASE:
        print("Debug: DATABASE is None, skipping find_in_json")
        return None # Trả về None nếu không nạp được "não"

    # Chỉ còn logic cho Kiến Trúc Sư XYZ
    triggers = DATABASE.get("chatbot_triggers", [])
    if not triggers: 
        print("Debug: chatbot_triggers is empty, skipping find_in_json")
        return None

    # Trả lời nhanh các câu hỏi đơn giản (để tiết kiệm API)
    if any(k in text for k in ["chào", "hello", "bạn là ai", "xin chào"]):
        resp = next((t["response"] for t in triggers if t["intent"] == "greet_hello"), None)
        if resp: return resp
        
    if any(k in text for k in ["giá", "chi phí", "báo giá", "bao nhiêu tiền"]):
        resp = next((t["response"] for t in triggers if t["intent"] == "ask_project_pricing"), None)
        if resp: return resp

    if any(k in text for k in ["liên hệ", "địa chỉ", "văn phòng"]):
        resp = next((t["response"] for t in triggers if t["intent"] == "ask_contact"), None)
        if resp: return resp
        
    if any(k in text for k in ["con bot này", "chatbot này", "ai làm bot"]):
        resp = next((t["response"] for t in triggers if t["intent"] == "ask_chatbot_pricing"), None)
        if resp: return resp

    # Nếu không khớp bất kỳ logic nào ở trên, trả về None
    return None


# ===================================
#  KẾT HỢP GPT ĐỂ TRẢ LỜI TỰ NHIÊN
# ===================================
def call_openai(user_text):
    """
    Gọi OpenAI (Smart-path) khi fast-path không xử lý được.
    """
    # 1. Thử trả lời nhanh bằng JSON trước
    local_reply = find_in_json(user_text)
    if local_reply:
        print("✅ Trả lời nhanh (JSON)")
        return local_reply

    # 2. Nếu không có → nhờ GPT trả lời tự nhiên (Smart-path)
    print("🧠 Trả lời thông minh (OpenAI)")
    
    if not DATABASE:
        return "Xin lỗi, 'não' của tôi đang được nạp, bạn thử lại sau 1 phút nhé! 😅"
    
    # Nạp toàn bộ "não" cho OpenAI đọc
    context = json.dumps(DATABASE, ensure_ascii=False, indent=2)
    
    # --- CẬP NHẬT SYSTEM PROMPT (Đơn giản hóa) ---
    system_prompt = (
        "Bạn là trợ lý AI của 'KTS Sáng Tạo (XYZ Studio)', một công ty kiến trúc. "
        "Nhiệm vụ của bạn là trả lời khách hàng một cách chuyên nghiệp, thân thiện, dựa trên dữ liệu JSON về công ty dưới đây:\n"
        f"{context}\n"
        "--- QUY TẮC ---\n"
        "- Hãy dùng dữ liệu trong 'chatbot_triggers' để trả lời các câu hỏi phổ biến (chào hỏi, giá, liên hệ) nếu có thể."
        "- Khi khách hỏi về dự án, triết lý, hãy phân tích JSON và trả lời."
        "- Luôn trả lời ngắn gọn, có cảm xúc, thêm emoji phù hợp."
        "- Đừng bịa thông tin không có trong JSON."
        "- Nếu khách hỏi về 'con bot này', hãy dùng intent 'ask_chatbot_pricing'."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text}
    ]

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini", # Dùng 4o-mini cho rẻ và nhanh
            messages=messages,
            temperature=0.7
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Lỗi OpenAI: {e}")
        # Trả về lỗi nếu OpenAI không hoạt động
        return "Xin lỗi, hệ thống AI đang hơi bận. Bạn thử lại sau 1 phút nha 😅"


# ===================================
#  GỬI TIN NHẮN VỀ FACEBOOK
# ===================================
def send_text(psid, text):
    if not psid or not text:
        return
    try:
        requests.post(FB_SEND_URL, json={
            "recipient": {"id": psid},
            "message": {"text": text}
        }, timeout=15)
        print(f"✅ Đã gửi tin nhắn tới {psid}")
    except Exception as e:
        print(f"❌ Lỗi gửi tin nhắn Facebook: {e}")


# ===================================
#  WEBHOOK FACEBOOK
# ===================================
@app.route("/webhook", methods=["GET"])
def verify():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        print("✅ Webhook đã xác thực!")
        return str(challenge)
    print("❌ Sai VERIFY_TOKEN!")
    return "Sai verify token", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    for entry in data.get("entry", []):
        for evt in entry.get("messaging", []):
            psid = evt.get("sender", {}).get("id")
            msg_obj = evt.get("message", {})
            msg_text = msg_obj.get("text")
            
            # Bỏ qua tin nhắn của chính Page
            if msg_obj.get("is_echo"):
                continue

            if psid and msg_text:
                print(f"👤 {psid} hỏi: {msg_text}")
                # Gọi hàm xử lý chính
                reply = call_openai(msg_text)
                print(f"🤖 Bot trả lời: {reply}")
                # Gửi trả lời về Facebook
                send_text(psid, reply)
                
    return "EVENT_RECEIVED", 200


@app.route("/health")
def health():
    # Kiểm tra xem DATABASE đã được nạp thành công hay chưa
    data_loaded = DATABASE is not None and "company_profile" in DATABASE
    return jsonify(
        ok=True, 
        data_loaded=data_loaded, 
        brand_name=DATABASE.get("company_profile", {}).get("brandName", "Not Loaded") if DATABASE else "Error Loading DB"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080))) # Đổi port 5000 thành 8080 (phổ biến hơn cho web)
