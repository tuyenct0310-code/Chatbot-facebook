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
# (MỚI) RÚT GỌN CONTEXT GỬI CHO AI
# ===================================
def find_relevant_context(user_text):
    """
    (HÀM MỚI - RAG ĐƠN GIẢN)
    Tìm và chỉ gửi những phần DỮ LIỆU LIÊN QUAN cho OpenAI.
    Đây là mấu chốt để tiết kiệm token ĐẦU VÀO (input).
    """
    print("🧠 Đang tìm context liên quan...")
    text_lower = user_text.lower()
    relevant_data = {}
    
    # Quét qua từng file (từng "não")
    for file_key, content in DATABASE.items():
        # Lấy tất cả dự án/sản phẩm (giả sử chúng nằm trong key này)
        projects = content.get("highlight_projects", [])
        products = content.get("products", [])
        
        found_items = []
        
        # 1. Tìm trong dự án
        for item in projects:
            name = item.get("name", "").lower()
            # Nếu tên dự án xuất hiện trong tin nhắn của khách
            if name and name in text_lower:
                found_items.append(item)
                
        # 2. Tìm trong sản phẩm
        for item in products:
            name = item.get("name", "").lower()
            # Nếu tên sản phẩm xuất hiện trong tin nhắn của khách
            if name and name in text_lower:
                found_items.append(item)

        # Nếu tìm thấy thứ gì đó liên quan trong file này
        if found_items:
            print(f"✅ Tìm thấy {len(found_items)} mục liên quan trong '{file_key}'")
            # Chúng ta chỉ gửi những mục tìm thấy, không gửi toàn bộ file
            if file_key not in relevant_data:
                 relevant_data[file_key] = {}
            
            # (Quan trọng) Chỉ thêm các mục liên quan
            relevant_data[file_key]["relevant_items_found"] = found_items
            
    if not relevant_data:
        print("⚠️ Không tìm thấy context sản phẩm/dự án cụ thể.")
        # Nếu không có gì liên quan, chỉ gửi thông báo
        return json.dumps({"ghi_chu": "Không tìm thấy dữ liệu sản phẩm/dự án liên quan. Chỉ trả lời dựa trên persona."})

    # Trả về chuỗi JSON của CHỈ NHỮNG DỮ LIỆU LIÊN QUAN
    print(f"✅ Đã rút gọn context, chỉ gửi: {list(relevant_data.keys())}")
    return json.dumps(relevant_data, ensure_ascii=False, indent=2)


# ===================================
#  KẾT HỢP GPT ĐỂ TRẢ LỜI TỰ NHIÊN
# ===================================
def call_openai(user_text):
    """
    (NÂNG CẤP) Gọi OpenAI với System Prompt "xịn" hơn, có "vai trò" (persona)
    và CONTEXT ĐÃ ĐƯỢC RÚT GỌN.
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
    
    # --- (THAY ĐỔI QUAN TRỌNG) ---
    # KHÔNG gửi toàn bộ DATABASE
    # CHỈ gửi những gì liên quan
    relevant_context = find_relevant_context(user_text)
    
    # Lấy persona từ file kientruc_xyz (hoặc file config chính)
    # (Giữ nguyên logic lấy persona của bạn)
    persona_data = DATABASE.get("kientruc_xyz", {}).get("persona", {})
    persona_role = persona_data.get("role", "Trợ lý AI")
    persona_tone = persona_data.get("tone", "Thân thiện, chuyên nghiệp")
    persona_goal = persona_data.get("goal", "Trả lời câu hỏi của khách hàng.")

    # --- SYSTEM PROMPT (HAY HƠN) ---
    system_prompt = (
        f"--- BẠN LÀ AI ---\n"
        f"Bạn là '{persona_role}', một trợ lý AI bán hàng.\n"
        f"Vai trò của bạn: {persona_role}\n"
        f"Tính cách (Tone): {persona_tone}\n"
        f"Mục tiêu (Goal): {persona_goal}\n\n"
        f"--- DỮ LIỆU LIÊN QUAN (ĐÃ LỌC) ---\n"
        f"Dưới đây là mẩu dữ liệu được trích xuất từ 'não' của bạn VÌ NÓ LIÊN QUAN đến câu hỏi của khách. Nếu không có gì, bạn chỉ cần trò chuyện bình thường.\n"
        f"{relevant_context}\n\n"
        "--- QUY TRÌNH LÀM VIỆC CỦA BẠN ---\n"
        "1. **Đọc câu hỏi của khách.**\n"
        "2. **Đọc DỮ LIỆU LIÊN QUAN:** Xem trong JSON bên trên có thông tin để trả lời không.\n"
        "3. **Trả lời:** Trả lời tự nhiên, ngắn gọn, *đúng với tính cách*.\n\n"
        "--- QUY TẮC VÀNG (ĐỂ TRẢ LỜI 'HAY' VÀ 'GỌN') ---\n"
        "- **(MỚI) NGẮN GỌN:** LUÔN trả lời ngắn gọn, súc tích, đi thẳng vào vấn đề. Tối đa 3-4 câu. Đừng viết văn dài dòng.\n"

        "- **NHẬP VAI:** Hành động như một chuyên gia tư vấn, không phải cái máy. Đừng bao giờ nói 'Tôi sẽ tìm trong JSON'. Hãy hành động như bạn *đã biết* câu trả lời.\n"
        "- **GỢI MỞ:** Sau khi trả lời, hãy hỏi một câu hỏi gợi mở *ngắn*. (Vd: 'Bạn muốn xem thêm ảnh dự án này không ạ?', 'Bạn cần tư vấn thêm gì ạ?').\n"
        "- **TUYỆT ĐỐI KHÔNG** bịa thông tin không có trong DỮ LIỆU LIÊN QUAN."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text}
    ]

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            # --- (THAY ĐỔI MỚI) ---
            # Giới hạn token ĐẦU RA để câu trả lời luôn ngắn gọn
            max_tokens=200 
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Lỗi OpenAI: {e}")
        # (Lưu ý: Lỗi 429 vẫn có thể xảy ra nếu bạn có quá nhiều người hỏi CÙNG LÚC,
        # nhưng lỗi do 1 request quá lớn sẽ được khắc phục)
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
