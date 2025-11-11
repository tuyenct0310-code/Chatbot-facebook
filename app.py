import os, requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

PAGE_TOKEN   = os.environ["PAGE_ACCESS_TOKEN"]
VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

def call_openai(user_text):
    # Tùy model bạn có: gpt-4o-mini/gpt-4.1-mini
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role":"system","content":"Bạn là trợ lý Facebook Page, trả lời ngắn gọn, tiếng Việt."},
            {"role":"user","content":user_text}
        ],
        temperature=0.3,
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
        return challenge or "OK"
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