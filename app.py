import os, json, random, requests
from flask import Flask, request, jsonify
from openai import OpenAI
import google.generativeai as genai

app = Flask(__name__)

# --- Lấy biến môi trường ---
PAGE_TOKEN     = os.environ.get("PAGE_ACCESS_TOKEN", "YOUR_PAGE_ACCESS_TOKEN_HERE")
VERIFY_TOKEN   = os.environ.get("VERIFY_TOKEN", "YOUR_VERIFY_TOKEN_HERE")
OPENAI_KEY     = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")
GEMINI_KEY     = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

# --- Khởi tạo Facebook ---
FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# --- Khởi tạo OpenAI ---
try:
    client = OpenAI(api_key=OPENAI_KEY)
    print("✅ Đã khởi tạo OpenAI Client")
except Exception as e:
    print(f"❌ Lỗi khởi tạo OpenAI: {e}")
    client = None

# --- Khởi tạo Gemini ---
try:
    genai.configure(api_key=GEMINI_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.0-pro') # Dòng 28 (hoặc 29)
    print("✅ Đã khởi tạo Gemini Model (1.0 Pro)") # Sửa luôn print
except Exception as e:
    print(f"❌ Lỗi khởi tạo Gemini: {e}")
    gemini_model = None


    
# Cấu hình an toàn (Safety Settings) cho Gemini
GEMINI_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
# Cấu hình sinh câu trả lời (Tương đương max_tokens)
GEMINI_GENERATION_CONFIG = {
  "temperature": 0.7,
  "top_p": 1,
  "top_k": 1,
  "max_output_tokens": 200, # Giống max_tokens=200 của OpenAI
}

# ===================================
#  NẠP KNOWLEDGE BASE (TẤT CẢ FILE)
# ===================================
def load_all_data(data_folder="data"):
    # ... (Giữ nguyên hàm này, không thay đổi) ...
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

DATABASE = load_all_data()


# ===================================
#  TÌM TRONG DỮ LIỆU JSON (Fast-path)
# ===================================
def find_in_json(user_text):
    # ... (Giữ nguyên hàm này, không thay đổi) ...
    text = user_text.lower()
    if not DATABASE: return None
    for file_key, content in DATABASE.items():
        triggers = content.get("chatbot_triggers", [])
        for trigger in triggers:
            keywords = trigger.get("keywords", [])
            if any(keyword in text for keyword in keywords):
                return random.choice(trigger.get("response", "").splitlines()) if isinstance(trigger.get("response"), str) else random.choice(trigger.get("response", [""]))
    return None

# ===================================
# (RAG) RÚT GỌN CONTEXT
# ===================================
def find_relevant_context(user_text):
    # ... (Giữ nguyên hàm này, không thay đổi) ...
    print("🧠 Đang tìm context liên quan...")
    text_lower = user_text.lower()
    relevant_data = {}
    for file_key, content in DATABASE.items():
        projects = content.get("highlight_projects", [])
        products = content.get("products", [])
        found_items = []
        for item in projects:
            name = item.get("name", "").lower()
            if name and name in text_lower: found_items.append(item)
        for item in products:
            name = item.get("name", "").lower()
            if name and name in text_lower: found_items.append(item)
        if found_items:
            print(f"✅ Tìm thấy {len(found_items)} mục liên quan trong '{file_key}'")
            if file_key not in relevant_data: relevant_data[file_key] = {}
            relevant_data[file_key]["relevant_items_found"] = found_items
    if not relevant_data:
        print("⚠️ Không tìm thấy context sản phẩm/dự án cụ thể.")
        return json.dumps({"ghi_chu": "Không tìm thấy dữ liệu sản phẩm/dự án liên quan. Chỉ trả lời dựa trên persona."})
    print(f"✅ Đã rút gọn context, chỉ gửi: {list(relevant_data.keys())}")
    return json.dumps(relevant_data, ensure_ascii=False, indent=2)

# --- Lấy Persona (Dùng chung cho cả 2 AI) ---
def get_persona_and_context(user_text):
    relevant_context = find_relevant_context(user_text)
    persona_data = DATABASE.get("kientruc_xyz", {}).get("persona", {})
    persona_role = persona_data.get("role", "Trợ lý AI")
    persona_tone = persona_data.get("tone", "Thân thiện, chuyên nghiệp")
    persona_goal = persona_data.get("goal", "Trả lời câu hỏi của khách hàng.")
    
    system_prompt = (
        f"--- BẠN LÀ AI ---\n"
        f"Bạn là '{persona_role}', một trợ lý AI bán hàng.\n"
        f"Vai trò của bạn: {persona_role}\n"
        f"Tính cách (Tone): {persona_tone}\n"
        f"Mục tiêu (Goal): {persona_goal}\n\n"
        f"--- DỮ LIỆU LIÊN QUAN (ĐÃ LỌC) ---\n"
        f"{relevant_context}\n\n"
        "--- QUY TRÌNH LÀM VIỆC CỦA BẠN ---\n"
        "1. **Đọc câu hỏi của khách.**\n"
        "2. **Đọc DỮ LIỆU LIÊN QUAN:** Xem trong JSON bên trên có thông tin để trả lời không.\n"
        "3. **Trả lời:** Trả lời tự nhiên, ngắn gọn, *đúng với tính cách*.\n\n"
        "--- QUY TẮC VÀNG (ĐỂ TRẢ LỜI 'HAY' VÀ 'GỌN') ---\n"
        "- **(MỚI) NGẮN GỌN:** LUÔN trả lời ngắn gọn, súc tích, đi thẳng vào vấn đề. Tối đa 3-4 câu.\n"
        "- **NHẬP VAI:** Hành động như một chuyên gia tư vấn...\n"
        "- **GỢI MỞ:** Sau khi trả lời, hãy hỏi một câu hỏi gợi mở *ngắn*...\n"
        "- **TUYỆT ĐỐI KHÔNG** bịa thông tin không có trong DỮ LIỆU LIÊN QUAN."
    )
    return system_prompt, user_text


# ===================================
#  LOGIC GỌI AI (ĐÃ SỬA)
# ===================================
def call_openai(system_prompt, user_text):
    """
    (ĐÃ SỬA) Hàm này SẼ GÂY LỖI (raise error) nếu thất bại,
    để hàm 'get_smart_reply' bắt và chuyển sang Gemini.
    """
    if not client:
        raise Exception("OpenAI client chưa được khởi tạo.")
        
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text}
    ]
    
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=200 
    )
    return resp.choices[0].message.content.strip()


def call_gemini(system_prompt, user_text):
    """
    (ĐÃ SỬA) Hàm này SẼ GÂY LỖI (raise error) nếu thất bại,
    để hàm 'get_smart_reply' bắt lỗi.
    """
    if not gemini_model:
        raise Exception("Gemini model chưa được khởi tạo.")
        
    # Khởi tạo model với system prompt (cách của Gemini)
    chat_model = genai.GenerativeModel(
        model_name='gemini-1.0-pro',
        generation_config=GEMINI_GENERATION_CONFIG,
        system_instruction=system_prompt,
        safety_settings=GEMINI_SAFETY_SETTINGS
    )
    
    resp = chat_model.generate_content(user_text)
    return resp.text.strip()


# ===================================
#  HÀM TỔNG (FAILOVER) (MỚI)
# ===================================
def get_smart_reply(user_text):
    """
    (HÀM MỚI) Hàm tổng điều phối:
    Thử JSON -> Thử OpenAI -> (Nếu hỏng) Thử Gemini -> (Nếu hỏng) Báo bận.
    """
    # 1. Thử trả lời nhanh (JSON)
    local_reply = find_in_json(user_text)
    if local_reply:
        print("✅ Trả lời nhanh (JSON)")
        return local_reply

    # 2. Chuẩn bị "Não"
    if not DATABASE:
        return "Xin lỗi, 'não' của tôi đang được nạp, bạn thử lại sau 1 phút nhé! 😅"
    
    system_prompt, user_text_for_ai = get_persona_and_context(user_text)

    # 3. Thử Ưu tiên 1: OpenAI
    try:
        print("🧠 Thử Ưu tiên 1: OpenAI (gpt-4o-mini)")
        reply = call_openai(system_prompt, user_text_for_ai)
        return reply
    except Exception as e_openai:
        print(f"⚠️ OpenAI thất bại: {e_openai}")
        
        # 4. OpenAI hỏng -> Thử Ưu tiên 2: Gemini
        try:
            print("🧠 Thử Ưu tiên 2: Gemini (1.0-pro')")
            reply = call_gemini(system_prompt, user_text_for_ai)
            return reply
        except Exception as e_gemini:
            print(f"❌ Gemini cũng thất bại: {e_gemini}")
            
            # 5. Cả hai đều hỏng
            print("❌ CẢ HAI HỆ THỐNG AI ĐỀU BẬN. Trả về tin nhắn dự phòng.")
            return "Xin lỗi, hệ thống AI đang hơi bận. Bạn thử lại sau 1 phút nha 😅"


# ===================================
#  GỬI TIN NHẮN VỀ FACEBOOK
# ===================================
def send_text(psid, text):
    # ... (Giữ nguyên hàm này, không thay đổi) ...
    if not psid or not text: return
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
    # ... (Giữ nguyên hàm này, không thay đổi) ...
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        print("✅ Webhook đã xác thực!")
        return str(challenge)
    print("❌ Sai VERIFY_TOKEN!")
    return "Sai verify token", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    # --- (ĐÃ SỬA ĐỂ GỌN HƠN) ---
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
                
                # Chỉ cần gọi 1 hàm duy nhất
                reply = get_smart_reply(msg_text) 
                
                print(f"🤖 Bot trả lời: {reply}")
                send_text(psid, reply)
                
    return "EVENT_RECEIVED", 200


@app.route("/health")
def health():
    # ... (Giữ nguyên hàm này, không thay đổi) ...
    data_loaded = DATABASE is not None and len(DATABASE.keys()) > 0
    return jsonify(
        ok=True, 
        data_loaded=data_loaded, 
        num_files_loaded=len(DATABASE.keys()) if DATABASE else 0,
        file_keys=list(DATABASE.keys()) if DATABASE else []
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))




