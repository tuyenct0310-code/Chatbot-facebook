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
#  NẠP KNOWLEDGE BASE (TẤT CẢ FILE)
# ===================================
def load_all_data(data_folder="data"):
    """
    Nạp TẤT CẢ file JSON trong thư mục /data.
    Mỗi tên file sẽ là một "key" trong DATABASE.
    Vd: data/product_sofa.json -> DATABASE['product_sofa'] = { ... }
    """
    database = {}
    if not os.path.exists(data_folder):
        print(f"❌ LỖI NGHIÊM TRỌNG: Không tìm thấy thư mục knowledge base '{data_folder}'.")
        return database
        
    for filename in os.listdir(data_folder):
        if filename.endswith(".json"):
            path = os.path.join(data_folder, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    # Dùng tên file (bỏ .json) làm key
                    file_key = filename.replace(".json", "")
                    database[file_key] = content
            except Exception as e:
                print(f"❌ Lỗi đọc file {filename}: {e}")
                
    print(f"✅ Đã nạp thành công các file: {list(database.keys())}")
    return database

# Nạp "não" cho bot khi khởi động
DATABASE = load_all_data()


# ===================================
#  TÌM TRONG DỮ LIỆU JSON (Fast-path)
# ===================================
def find_in_json(user_text):
    """
    Tìm các câu trả lời nhanh (fast-path) chung chung, KHÔNG liên quan đến sản phẩm.
    Để tiết kiệm API OpenAI.
    """
    text = user_text.lower()
    
    if not DATABASE:
        return None # Trả về None nếu không nạp được "não"

    # Tìm trong file kientruc_xyz (hoặc 1 file config chung)
    # Giả sử file config của bạn tên là 'kientruc_xyz.json'
    config_triggers = DATABASE.get("kientruc_xyz", {}).get("chatbot_triggers", [])
    
    if not config_triggers:
        # Nếu không có file config, tự tạo trigger "giá chatbot"
         if any(k in text for k in ["con bot này", "chatbot này", "ai làm bot"]):
            return "Tôi là một chatbot AI demo. Nếu bạn muốn một chatbot tương tự, vui lòng liên hệ [Email/SĐT Của Bạn] nhé!"
         return None

    # Trả lời nhanh các câu hỏi chung
    if any(k in text for k in ["chào", "hello", "xin chào"]):
        resp = next((t["response"] for t in config_triggers if t["intent"] == "greet_hello"), None)
        if resp: return resp
        
    if any(k in text for k in ["con bot này", "chatbot này", "ai làm bot"]):
        resp = next((t["response"] for t in config_triggers if t["intent"] == "ask_chatbot_pricing"), None)
        if resp: return resp
        
    # Câu hỏi về GIÁ và LIÊN HỆ của sản phẩm -> Để OpenAI tự trả lời
    # Vì bot cần biết khách hỏi về sản phẩm nào trước.

    return None


# ===================================
#  KẾT HỢP GPT ĐỂ TRẢ LỜI TỰ NHIÊN
# ===================================
def call_openai(user_text):
    """
    Gọi OpenAI (Smart-path) cho tất cả các câu hỏi phức tạp về sản phẩm.
    """
    # 1. Thử trả lời nhanh bằng JSON trước (chỉ câu chào, câu meta)
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
    
    # --- SYSTEM PROMPT "ĐA SẢN PHẨM" CỰC KỲ QUAN TRỌNG ---
    system_prompt = (
        "Bạn là một trợ lý bán hàng AI thông minh. 'Não' của bạn chứa thông tin về TẤT CẢ các sản phẩm công ty đang bán, được lưu trong một file JSON lớn dưới đây. "
        "Mỗi key cấp cao nhất trong JSON là mã sản phẩm (ví dụ: 'product_sofa_A', 'kientruc_xyz').\n"
        f"{context}\n"
        "--- QUY TRÌNH LÀM VIỆC CỦA BẠN ---\N"
        "1. **Đọc câu hỏi của khách.** (Vd: 'Cho tôi hỏi giá Nhà Hàng Hiên')."
        "2. **Quét JSON:** Tự động tìm xem 'Nhà Hàng Hiên' nằm ở đâu trong JSON (Nó nằm trong 'kientruc_xyz' -> 'highlight_projects')."
        "3. **Tìm thông tin liên quan:** Tìm giá, mô tả, hoặc bất cứ thứ gì khách hỏi."
        "4. **Trả lời:** Trả lời câu hỏi của khách một cách tự nhiên, ngắn gọn, thân thiện."
        "--- QUY TẮC ---\N"
        "- Đừng bao giờ nói 'Tôi sẽ tìm trong JSON'. Hãy hành động như bạn *đã biết* câu trả lời."
        "- Nếu khách hỏi về 2 sản phẩm (Vd: 'so sánh sofa A và sofa B'), hãy tự tin tra cứu cả 2 file ('product_sofa_A' và 'product_sofa_B') và so sánh."
        "- Luôn trả lời ngắn gọn, có cảm xúc, thêm emoji."
        "- **Tuyệt đối không** bịa thông tin không có trong JSON."
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
        return "Xin lỗi, hệ thống AI đang hơi bận. Bạn thử lại sau 1 phút nha 😅"


# ===================================
#  GỬI TIN NHẮN VỀ FACEBOOK
# ===================================
# (Giữ nguyên không đổi)
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
# (Giữ nguyên không đổi)
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
    data_loaded = DATABASE is not None and len(DATABASE.keys()) > 0
    return jsonify(
        ok=True, 
        data_loaded=data_loaded, 
        num_files_loaded=len(DATABASE.keys()) if DATABASE else 0,
        file_keys=list(DATABASE.keys()) if DATABASE else []
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080))) # Đổi port 5000 thành 8080 (phổ biến hơn cho web)
