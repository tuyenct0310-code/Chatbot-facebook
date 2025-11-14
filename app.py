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
    print("✅ OpenAI đã khởi tạo")
except Exception as e:
    print("❌ Lỗi OpenAI:", e)
    client = None

# ==========================
#  ƯU TIÊN JSON
# ==========================
FILE_PRIORITY_ORDER = [
    "quangcao_chatbot_ctt",
    "kientruc_xyz",
    "oc_ngon_18"
]

# ==========================
#  LOAD TẤT CẢ JSON
# ==========================
def load_all_data(folder="data"):
    db = {}
    if not os.path.exists(folder):
        print("❌ Không có thư mục data/")
        return db

    for file in os.listdir(folder):
        if file.endswith(".json"):
            try:
                with open(os.path.join(folder, file), "r", encoding="utf8") as f:
                    key = file.replace(".json", "")
                    db[key] = json.load(f)
            except Exception as e:
                print("❌ Lỗi đọc file:", file, e)

    print("📂 Đã load JSON:", list(db.keys()))
    return db

DATABASE = load_all_data()

# ==========================
#  MATCH JSON CHÍNH XÁC
# ==========================
def find_in_json(text):
    if not DATABASE:
        return None

    t = text.lower()

    # Ưu tiên file trước
    for file_key in FILE_PRIORITY_ORDER:
        data = DATABASE.get(file_key)
        if not data:
            continue

        for tr in data.get("chatbot_triggers", []):
            keywords = [k.lower() for k in tr.get("keywords", [])]

            # match từ khóa chính xác (không match sai kiểu chứa 1 phần)
            if any(k in t for k in keywords):
                print(f"🎯 JSON match → {file_key}")
                resp = tr.get("response", "")
                if isinstance(resp, list):
                    return random.choice(resp)
                return random.choice(resp.splitlines())

    return None

# ==========================
#  XÁC ĐỊNH DỊCH VỤ (INTENT)
# ==========================
def detect_intent(user_text):
    t = user_text.lower()
    matches = []

    for file_key, data in DATABASE.items():
        file_keywords = []
        for tr in data.get("chatbot_triggers", []):
            file_keywords.extend([k.lower() for k in tr.get("keywords", [])])

        if any(k in t for k in file_keywords):
            matches.append(file_key)

    if matches:
        print("🧭 Intent:", matches[0])
        return matches[0]

    print("⚠️ Không xác định được intent")
    return None

# ==========================
#  RÚT GỌN CONTEXT CHẶT CHẼ
# ==========================
def find_relevant_context(user_text):
    intent = detect_intent(user_text)
    if not intent:
        return "{}"

    content = DATABASE.get(intent, {})

    ctx = {
        "triggers": content.get("chatbot_triggers", []),
        "products": content.get("products", []),
        "projects": content.get("highlight_projects", [])
    }

    print("📦 Gửi context từ:", intent)
    return json.dumps(ctx, ensure_ascii=False)

# ==========================
#  PERSONA + STRICT MODE
# ==========================
def get_persona_and_context(user_text):
    ctx = find_relevant_context(user_text)

    persona = {}
    for key in FILE_PRIORITY_ORDER:
        p = DATABASE.get(key, {}).get("persona", {})
        if p:
            persona = p
            print("👤 Persona từ:", key)
            break

    system_prompt = f"""
Bạn là {persona.get("role", "Trợ lý AI")}.
Tính cách: {persona.get("tone", "Rõ ràng, chuyên nghiệp")}.
Mục tiêu: {persona.get("goal", "Hỗ trợ khách hàng.")}.

--- CÂU HỎI KHÁCH ---
"{user_text}"

--- CONTEXT DUY NHẤT ĐƯỢC DÙNG ---
{ctx}

--- QUY TẮC CHỐNG NHẦM CHỦ ĐỀ ---
1. Chỉ trả lời theo đúng nội dung câu hỏi.
2. Không trả lời sang dịch vụ khác.
3. Không tạo thêm dữ liệu ngoài context.
4. Nếu câu hỏi chưa rõ → phải hỏi lại.
5. Trả lời ngắn gọn 2–3 câu.
"""

    return system_prompt, user_text

# ==========================
#  OPENAI GỌI CHÍNH XÁC
# ==========================
def call_openai(system_prompt, user_text):
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        temperature=0.15,  # chống bịa
        max_tokens=250
    )
    return resp.choices[0].message.content.strip()

# ==========================
#  LOGIC TRẢ LỜI
# ==========================
def get_smart_reply(user_text):
    # 1. JSON trước
    fast = find_in_json(user_text)
    if fast:
        return fast

    if not DATABASE:
        return "Dữ liệu chưa sẵn sàng, thử lại sau 1 phút."

    # 2. OpenAI
    system_prompt, text = get_persona_and_context(user_text)
    try:
        print("🤖 AI trả lời...")
        return call_openai(system_prompt, text)
    except Exception as e:
        print("❌ Lỗi AI:", e)
        return "Hệ thống đang bị quá tải, bạn thử lại sau nhé."

# ==========================
#  GỬI TIN
# ==========================
def send_text(psid, text):
    try:
        requests.post(FB_SEND_URL, json={
            "recipient": {"id": psid},
            "message": {"text": text}
        }, timeout=15)
        print("📨 Gửi:", psid)
    except Exception as e:
        print("❌ FB Send Error:", e)

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

            psid  = evt.get("sender", {}).get("id")
            text = evt.get("message", {}).get("text")

            if psid and text:
                print(f"👤 {psid}: {text}")
                reply = get_smart_reply(text)
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
