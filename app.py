import os, json, random, requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# ==========================
#  ENV
# ==========================
PAGE_TOKEN   = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
OPENAI_KEY   = os.environ.get("OPENAI_API_KEY", "")

FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# ==========================
#  OpenAI
# ==========================
try:
    client = OpenAI(api_key=OPENAI_KEY)
    print("✅✅✅ PHIÊN BẢN CODE MỚI NHẤT ĐÃ CHẠY ✅✅✅")
except Exception as e:
    print("❌ Lỗi OpenAI:", e)
    client = None

# ==========================
#  (MỚI) THỨ TỰ ƯU TIÊN FILE JSON
# ==========================
# Bot sẽ kiểm tra file "quangcao_chatbot_ctt" trước,
# rồi mới tới "kientruc_xyz", và cuối cùng là "oc_ngon_18".
FILE_PRIORITY_ORDER = [
    "quangcao_chatbot_ctt",
    "kientruc_xyz",
    "oc_ngon_18"
]

# ==========================
#  LOAD ALL JSON IN /data
# ==========================
def load_all_data(folder="data"):
    db = {}
    if not os.path.exists(folder):
        print("❌ Không tìm thấy thư mục 'data'")
        return db

    for file in os.listdir(folder):
        if file.endswith(".json"):
            try:
                with open(os.path.join(folder, file), "r", encoding="utf8") as f:
                    key = file.replace(".json", "")
                    db[key] = json.load(f)
            except Exception as e:
                print("❌ Lỗi đọc", file, e)

    print("✅ Đã nạp:", list(db.keys()))
    return db

DATABASE = load_all_data()

# ==========================
#  TÌM TRONG JSON (Fast path) - (ĐÃ SỬA)
# ==========================
def find_in_json(text):
    if not DATABASE:
        return None

    t = text.lower()

    # (MỚI) Lặp qua danh sách ƯU TIÊN
    for file_key in FILE_PRIORITY_ORDER:
        data = DATABASE.get(file_key) # Lấy đúng file
        if not data:
            continue # Bỏ qua nếu file này không được nạp

        triggers = data.get("chatbot_triggers", [])
        for tr in triggers:
            keywords = tr.get("keywords", [])
            if any(k in t for k in keywords):
                # TÌM THẤY -> Trả lời ngay
                print(f"✅ Trả lời nhanh (JSON - Ưu tiên từ file: {file_key})")
                resp = tr.get("response", "")
                if isinstance(resp, list):
                    return random.choice(resp)
                return random.choice(resp.splitlines())

    # (MỚI) Lặp qua các file CÒN LẠI
    # (Phòng trường hợp bạn thêm file mới mà quên cập nhật list)
    for file_key, data in DATABASE.items():
        if file_key in FILE_PRIORITY_ORDER:
            continue # Bỏ qua vì đã kiểm tra ở trên

        triggers = data.get("chatbot_triggers", [])
        for tr in triggers:
            keywords = tr.get("keywords", [])
            if any(k in t for k in keywords):
                print(f"✅ Trả lời nhanh (JSON - File: {file_key})")
                resp = tr.get("response", "")
                if isinstance(resp, list):
                    return random.choice(resp)
                return random.choice(resp.splitlines())
                
    return None # Không tìm thấy ở bất kỳ file nào

# ==========================
#  CONTEXT FILTER (RAG mini)
# ==========================
def find_relevant_context(user_text):
    text = user_text.lower()
    result = {}

    # (Lưu ý: Hàm này vẫn quét TẤT CẢ các file để gửi cho AI)
    for file_key, content in DATABASE.items():
        projects = content.get("highlight_projects", [])
        products = content.get("products", [])
        found = []

        for item in projects:
            if item.get("name", "").lower() in text:
                found.append(item)

        for item in products:
            if item.get("name", "").lower() in text:
                found.append(item)

        if found:
            result[file_key] = {"relevant_items_found": found}

    if not result:
        print("⚠️ Không tìm thấy context sản phẩm/dự án cụ thể.")
        return json.dumps({"note": "Không tìm thấy sản phẩm/dự án phù hợp."})
    
    print(f"✅ Đã rút gọn context, chỉ gửi: {list(result.keys())}")
    return json.dumps(result, ensure_ascii=False, indent=2)

# ==========================
#  PERSONA
# ==========================
def get_persona_and_context(user_text):
    ctx = find_relevant_context(user_text)
    
    # (Quan trọng) Persona giờ sẽ lấy từ file ưu tiên
    # Nó sẽ thử lấy persona từ 'quangcao_chatbot_ctt', 
    # nếu không có, nó sẽ thử 'kientruc_xyz'
    persona = {}
    for file_key in FILE_PRIORITY_ORDER:
        persona_data = DATABASE.get(file_key, {}).get("persona", {})
        if persona_data:
            persona = persona_data
            print(f"ℹ️ Đã lấy Persona từ file: {file_key}")
            break
    
    # Nếu không file ưu tiên nào có persona, lấy đại 1 cái
    if not persona:
         persona = DATABASE.get("kientruc_xyz", {}).get("persona", {})

    role = persona.get("role", "Trợ lý AI")
    tone = persona.get("tone", "Thân thiện, chuyên nghiệp")
    goal = persona.get("goal", "Hỗ trợ khách hàng.")

    system_prompt = f"""
Bạn là {role}.
Tính cách: {tone}.
Mục tiêu: {goal}.

--- DATA LIÊN QUAN ---
{ctx}

--- QUY TẮC ---
- Trả lời NGẮN GỌN (3-4 câu).
- Không bịa thông tin không có trong dữ liệu.
- Hỏi lại khách 1 câu để gợi mở.
"""

    return system_prompt, user_text

# ==========================
#  CALL OPENAI
# ==========================
def call_openai(system_prompt, user_text):
    if not client:
        raise Exception("OpenAI chưa khởi tạo")

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        temperature=0.7,
        max_tokens=200
    )

    return resp.choices[0].message.content.strip()

# ==========================
#  LOGIC TRẢ LỜI
# ==========================
def get_smart_reply(user_text):
    # 1. JSON trước (Đã ưu tiên theo file)
    fast = find_in_json(user_text)
    if fast:
        return fast # Đã bao gồm log bên trong find_in_json

    if not DATABASE:
        return "Dữ liệu đang nạp, thử lại sau 1 phút nha 😅"

    system_prompt, text = get_persona_and_context(user_text)

    # 2. Chỉ gọi OpenAI
    try:
        print("🧠 Trả lời thông minh: OpenAI (gpt-4o-mini)")
        return call_openai(system_prompt, text)
    except Exception as e:
        print(f"❌ OpenAI thất bại: {e}")
        return "Hệ thống AI đang hơi bận. Bạn thử lại sau 1 phút nha 😅"

# ==========================
#  SEND FACEBOOK
# ==========================
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
        print("❌ FB lỗi:", e)

# ==========================
#  WEBHOOK
# ==========================
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Sai verify token", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}

    for entry in data.get("entry", []):
        for evt in entry.get("messaging", []):
            if evt.get("message", {}).get("is_echo"):
                continue

            psid = evt.get("sender", {}).get("id")
            msg = evt.get("message", {}).get("text")

            if psid and msg:
                print(f"👤 {psid} hỏi: {msg}")
                reply = get_smart_reply(msg) 
                print(f"🤖 Bot trả lời: {reply}")
                send_text(psid, reply)

    return "OK", 200

@app.route("/health")
def health():
    return jsonify(
        ok=True,
        num_files=len(DATABASE),
        files=list(DATABASE.keys())
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

