import os, requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

PAGE_TOKEN   = os.environ["PAGE_ACCESS_TOKEN"]
VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# ==============================
# DỮ LIỆU MENU
# ==============================
MENU = {
    "Món chiên - nướng": {
        "hàu nướng mỡ hành": "10k/con",
        "hàu nướng phô mai": "15k/con",
        "hàu sống": "10k/con",
        "bánh mì nướng phô mai": "12k/miếng",
        "nem chua rán": "55k",
        "khoai tây chiên": "25k",
        "khoai tây lắc phô mai": "30k",
        "khoai lang kén": "25k",
        "ngô chiên bơ": "30k",
        "xúc xích": "10k - 15k",
        "lạp xưởng": "15k"
    },
    "Món nhậu": {
        "chân gà chiên mắm": "12k/c",
        "chân gà ngâm sả tắc": "60k",
        "chân gà sốt thái": "65k",
        "trứng cút luộc": "40k",
        "trứng cút xào me": "55k",
        "dưa chuột": "10k",
        "hoa quả": "15k"
    },
    "Lẩu - Mỳ": {
        "lẩu thái tomyum": "250k",
        "mỳ thái xúc xích": "35k",
        "mỳ thái bò": "40k",
        "mỳ thái bò xúc xích": "45k",
        "mỳ thái thập cẩm": "55k"
    },
    "Topping": {
        "ba chỉ bò 250g": "80k",
        "xúc xích": "30k",
        "đậu hũ phô mai": "40k",
        "viên thả lẩu mix": "40k",
        "tôm / mực 200g": "70k",
        "nấm": "15k",
        "rau": "15k",
        "mì": "5k/g",
        "bánh mì": "5k/c"
    },
    "Ốc biển": {
        "ốc hương trứng muối": "135k",
        "ốc hương sữa dừa": "130k",
        "ốc hương bơ tỏi": "130k",
        "ốc hương bơ cay": "130k",
        "ốc hương cháy tỏi": "130k",
        "ốc hương hấp sả": "125k",
        "ốc mỡ trứng muối": "135k",
        "ốc mỡ sữa dừa": "130k",
        "ốc mỡ bơ tỏi": "130k",
        "ốc mỡ bơ cay": "130k",
        "ốc mỡ cháy tỏi": "130k",
        "ốc mỡ hấp sả": "125k"
    },
    "Ốc đồng": {
        "ốc vặn hấp sả": "35k",
        "ốc vặn luộc mắm": "35k",
        "ốc vặn hấp thái": "35k",
        "ốc mít hấp sả": "70k",
        "ốc mít luộc mắm": "70k",
        "ốc mít hấp thái": "70k",
        "ốc mít sốt me": "75k",
        "ốc lẫn hấp sả": "60k",
        "ốc lẫn luộc mắm": "60k",
        "ốc lẫn hấp thái": "60k"
    },
    "Ngao": {
        "ngao hấp sả": "40k",
        "ngao hấp thái": "50k",
        "ngao sốt trứng muối": "70k",
        "ngao sữa dừa": "60k",
        "ngao bơ tỏi": "60k",
        "ngao bơ cay": "60k",
        "ngao sốt me": "60k"
    },
    "Đồ uống": {
        "pepsi": "15k",
        "trà đá": "5k",
        "trà đá ca": "20k",
        "trà chanh": "12k",
        "trà quất": "12k",
        "nước khoáng": "8k",
        "bia hn": "18k",
        "bia sg": "18k"
    }
}

# ==============================
# HÀM TRA CỨU MENU
# ==============================
def find_in_menu(user_text):
    text = user_text.lower()
    for category, items in MENU.items():
        for name, price in items.items():
            if name in text:
                return f"👉 {name.title()} ({category}) có giá {price} nhé!"
    return None

# ==============================
# GỌI OPENAI HOẶC TRA MENU
# ==============================
def call_openai(user_text):
    # Nếu tin nhắn có món ăn trong menu
    menu_reply = find_in_menu(user_text)
    if menu_reply:
        return menu_reply

    # Nếu không, fallback qua AI
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Bạn là chatbot quán Ốc Ngon 18, nói ngắn gọn, vui vẻ, tiếng Việt."},
            {"role": "user", "content": user_text}
        ],
        temperature=0.4,
    )
    return resp.choices[0].message.content.strip()


def send_text(psid, text):
    requests.post(FB_SEND_URL, json={
        "recipient": {"id": psid},
        "message": {"text": text}
    }, timeout=15)

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
            # text message
            msg = evt.get("message", {}).get("text")
            # postback (menu/quick replies)
            if not msg and "postback" in evt:
                msg = evt["postback"].get("payload") or evt["postback"].get("title")

            if psid and msg:
                try:
                    reply = call_openai(msg)
                except Exception as e:
                    reply = "Xin lỗi, hệ thống đang bận. Vui lòng thử lại sau."
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

