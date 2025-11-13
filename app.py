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
    (NÂNG CẤP) Tự động quét keywords trong chatbot_triggers của TẤT CẢ file.
    """
    text = user_text.lower()
    
    if not DATABASE:
        return None

    # Vòng lặp quét tất cả các "não" (file)
    for file_key, content in DATABASE.items():
        triggers = content.get("chatbot_triggers", [])
        
        for trigger in triggers:
            keywords = trigger.get("keywords", [])
            # Nếu bất kỳ từ khóa nào trong list keywords xuất hiện trong tin nhắn
            if any(keyword in text for keyword in keywords):
                # Trả về câu trả lời đã định sẵn
                return random.choice(trigger.get("response", "").splitlines()) if isinstance(trigger.get("response"), str) else random.choice(trigger.get("response", [""]))

    # Nếu không khớp bất kỳ logic nào ở trên, trả về None
    return None


# ===================================
#  KẾT HỢP GPT ĐỂ TRẢ LỜI TỰ NHIÊN
# ===================================
def call_openai(user_text):
    """
    (NÂNG CẤP) Gọi OpenAI với System Prompt "xịn" hơn, có "vai trò" (persona).
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
    
    # Lấy persona từ file kientruc_xyz (hoặc file config chính)
    persona_data = DATABASE.get("kientruc_xyz", {}).get("persona", {})
    persona_role = persona_data.get("role", "Trợ lý AI")
    persona_tone = persona_data.get("tone", "Thân thiện, chuyên nghiệp")
    persona_goal = persona_data.get("goal", "Trả lời câu hỏi của khách hàng.")

    # --- SYSTEM PROMPT (HAY HƠN) ---
    system_prompt = (
        f"--- BẠN LÀ AI ---\n"
        f"Bạn là '{persona_role}', một trợ lý AI bán hàng. 'Não' của bạn chứa thông tin về TẤT CẢ các sản phẩm và dịch vụ của công ty, được lưu trong file JSON lớn dưới đây.\n"
        f"Vai trò của bạn: {persona_role}\n"
        f"Tính cách (Tone): {persona_tone}\n"
        f"Mục tiêu (Goal): {persona_goal}\n\n"
        f"--- DỮ LIỆU (NÃO) CỦA BẠN ---\n"
        f"{context}\n\n"
        "--- QUY TRÌNH LÀM VIỆC CỦA BẠN ---\n"
        "1. **Đọc câu hỏi của khách.** (Vd: 'Cho tôi hỏi giá Nhà Hàng Hiên').\n"
        "2. **Quét JSON:** Tự động tìm xem 'Nhà Hàng Hiên' nằm ở đâu trong JSON (Nó nằm trong 'kientruc_xyz' -> 'highlight_projects').\n"
        "3. **Trả lời:** Trả lời câu hỏi của khách một cách tự nhiên, ngắn gọn, thân thiện, và *đúng với tính cách* của bạn.\n\n"
        "--- QUY TẮC VÀNG (ĐỂ TRẢ LỜI 'HAY') ---\n"
        "- **NHẬP VAI:** Hành động như một chuyên gia tư vấn tinh tế, không phải cái máy. Đừng bao giờ nói 'Tôi sẽ tìm trong JSON'. Hãy hành động như bạn *đã biết* câu trả lời.\n"
        "- **GỢI MỞ:** Sau khi trả lời, hãy *luôn* chủ động hỏi một câu hỏi gợi mở. (Vd: 'Bạn có muốn xem thêm hình ảnh chi tiết của dự án này không ạ?', 'Bạn dự định xây nhà trên diện tích bao nhiêu m2?').\n"
        "- **SO SÁNH:** Nếu khách hỏi so sánh 2 sản phẩm, hãy tự tin tra cứu cả 2 và so sánh.\n"
        "- **TUYỆT ĐỐI KHÔNG** bịa thông tin không có trong JSON."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text}
    ]

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
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
            
            if msg_obj.get("is_echo"):
                continue

            if psid and msg_text:
                print(f"👤 {psid} hỏi: {msg_text}")
                reply = call_openai(msg_text)
                print(f"🤖 Bot trả lời: {reply}")
                send_text(psid, reply)
                
    return "EVENT_RECEIVED", 200


@app.route("/health")
def health():
    data_loaded = DATABASE is not None and len(DATABASE.keys()) > 0
    return jsonify(
        ok=True, 
        data_loaded=data_loaded, 
        num_files_loaded=len(DATABASE.keys()) if DATABASE else 0,
        file_keys=list(DATABASE.keys()) if DATABASE else []
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
