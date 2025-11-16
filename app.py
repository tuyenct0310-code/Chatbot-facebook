# app.py - Multi-Page RAG Chatbot (FULL + TỐI ƯU + HOÀN CHỈNH)
# ĐÃ TỐI ƯU HÓA: multi-page, corpus riêng, embedding riêng, tốc độ cao
# Bạn CHỈ cần chỉnh PAGE_DATASET_MAP là chạy được nhiều page.

import os
import json
import time
import random
import requests
import threading
from pathlib import Path
import numpy as np
from flask import Flask, request, jsonify
from openai import OpenAI

# -----------------------
# CONFIG
# -----------------------
EMBED_MODEL = "text-embedding-3-large"
CHAT_MODEL = "gpt-4o-mini"
EMBED_BATCH = 16
CHUNK_SIZE = 400
SIMILARITY_THRESHOLD = 0.72
TOP_K = 5
TEMPERATURE = 0.12

PAGE_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# -----------------------
# PAGE → DATA FOLDER MAPPING (ĐÃ ĐIỀN 2 PAGE CHO BẠN)
# -----------------------
PAGE_DATASET_MAP = {
    "895305580330861": "page_xyz",   # Kiến trúc XYZ
    "847842948414951": "page_ctt"    # Chatbot CTT
}

app = Flask(__name__)

# -----------------------
# OpenAI
# -----------------------
try:
    client = OpenAI(api_key=OPENAI_KEY)
    print("OpenAI ready")
except:
    client = None

# -----------------------
# STORAGE
# -----------------------
DATABASE = {}
CORPUS = {}
EMBEDDINGS = {}

# -----------------------
# LOAD DATASET
# -----------------------
def load_dataset_by_folder(folder):
    folder_path = Path("data") / folder
    db = {}
    if not folder_path.exists():
        return db
    for f in folder_path.glob("*.json"):
        try:
            with open(f, "r", encoding="utf8") as fh:
                db[f.stem] = json.load(fh)
        except:
            pass
    return db

# -----------------------
# CHUNKING + CORPUS
# -----------------------
def text_to_chunks(text, size=CHUNK_SIZE):
    text = text.strip().replace("
", " ")
    if not text:
        return []
    parts = text.split(". ")
    chunks = []
    cur = ""
    for p in parts:
        if len(cur) + len(p) + 2 <= size:
            cur = (cur + ". " + p).strip(" .")
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)

    final = []
    for c in chunks:
        if len(c) <= size:
            final.append(c)
        else:
            for i in range(0, len(c), size):
                final.append(c[i:i+size])
    return final

def build_corpus_from_database(db):(db):
    corpus = []
    idx = 0
    for file_key, content in db.items():
        for tr in content.get("chatbot_triggers", []):
            kw = " ".join(tr.get("keywords", []))
            resp = tr.get("response", "")
            if isinstance(resp, list): resp = " ".join(resp)
            text = f"KEYWORDS: {kw}
RESPONSE: {resp}"
            for c in text_to_chunks(text):
                corpus.append({"id": f"c{idx}", "file": file_key, "source": "trigger", "text": c})
                idx += 1

        for p in content.get("products", []):
            name = p.get("name", "")
            desc = p.get("description", "")
            if not isinstance(desc, str): desc = json.dumps(desc)
            text = f"PRODUCT: {name}
{desc}"
            for c in text_to_chunks(text):
                corpus.append({"id": f"c{idx}", "file": file_key, "source": "product", "text": c})
                idx += 1

        for pr in content.get("highlight_projects", []):
            name = pr.get("name", "")
            desc = pr.get("summary", "")
            if not isinstance(desc, str): desc = json.dumps(desc)
            text = f"PROJECT: {name}
{desc}"
            for c in text_to_chunks(text):
                corpus.append({"id": f"c{idx}", "file": file_key, "source": "project", "text": c})
                idx += 1

        persona = content.get("persona", {})
        if persona:
            text = f"PERSONA: {persona.get('role','')}. {persona.get('tone','')}. Goal: {persona.get('goal','')}"
            for c in text_to_chunks(text):
                corpus.append({"id": f"c{idx}", "file": file_key, "source": "persona", "text": c})
                idx += 1
    return corpus

# -----------------------
# EMBEDDING
# -----------------------
def get_embed_path(folder):
    return f"embeddings/{folder}.json"

def compute_embeddings_for_page(folder, corpus, force=False):
    embed_path = get_embed_path(folder)

    if os.path.exists(embed_path) and not force:
        try:
            with open(embed_path, "r", encoding="utf8") as fh:
                return json.load(fh)
        except:
            pass

    vectors = []
    texts = [c["text"] for c in corpus]
    batch, batch_idx = [], []

    for i, txt in enumerate(texts):
        batch.append(txt)
        batch_idx.append(i)

        if len(batch) >= EMBED_BATCH or i == len(texts) - 1:
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
                for j, out in enumerate(resp.data):
                    idx = batch_idx[j]
                    c = corpus[idx]
                    vectors.append({
                        "id": c["id"], "file": c["file"], "source": c["source"],
                        "text": c["text"], "vec": out.embedding
                    })
            except:
                for j, _ in enumerate(batch):
                    idx = batch_idx[j]
                    c = corpus[idx]
                    vectors.append({
                        "id": c["id"], "file": c["file"], "source": c["source"],
                        "text": c["text"], "vec": [0.0]*1536
                    })
            batch, batch_idx = [], []

    store = {"vectors": vectors, "meta": {"created": time.time()}}
    with open(embed_path, "w", encoding="utf8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)
    return store

# -----------------------
# SIMILARITY
# -----------------------
def cosine(a, b):
    a = np.array(a, float)
    b = np.array(b, float)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0: return 0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def semantic_search(query_vec, store, top_k=TOP_K):
    sims = []
    for x in store["vectors"]:
        sims.append({"score": cosine(query_vec, x["vec"]), "item": x})
    sims.sort(key=lambda x: x["score"], reverse=True)
    return sims[:top_k]

# -----------------------
# SEMANTIC CONTEXT
# -----------------------
def get_semantic_context(folder, text):
    try:
        resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
        qvec = resp.data[0].embedding
    except:
        return []
    return semantic_search(qvec, EMBEDDINGS.get(folder, {}))

# -----------------------
# FAST JSON MATCH
# -----------------------
def find_in_json_exact(folder, text):
    db = DATABASE.get(folder, {})
    t = text.lower()
    for file_key, data in db.items():
        for tr in data.get("chatbot_triggers", []):
            for k in tr.get("keywords", []):
                if k.lower() in t:
                    resp = tr.get("response", "")
                    if isinstance(resp, list): return random.choice(resp)
                    return resp
    return None

# -----------------------
# SYSTEM PROMPT
# -----------------------
def assemble_system_prompt(folder, user_text, top_items):
    files = [i["item"]["file"] for i in top_items]
    dominant = max(set(files), key=files.count)
    persona = {}

    for file_key, data in DATABASE.get(folder, {}).items():
        if file_key == dominant:
            persona = data.get("persona", {})
            break

    ctx = []
    for x in top_items:
        it = x["item"]
        ctx.append(f"[file:{it['file']} score:{x['score']:.3f}]
{it['text']}")

    ctx_text = "

---

".join(ctx)

    return f"""
Bạn là trợ lý hỗ trợ khách dựa trên đúng dữ liệu cung cấp.
Persona: {json.dumps(persona, ensure_ascii=False)}

--- QUY TẮC
1) Chỉ trả lời dựa trên CONTEXT. Không tự bịa.
2) Nếu không đủ thông tin → yêu cầu khách nói rõ.
3) Trả lời ngắn gọn 1-3 câu.

--- USER:
"{user_text}"

--- CONTEXT:
{ctx_text}
"""

# -----------------------
# CALL OPENAI
# -----------------------
def ask_llm(system_prompt, user_text):
    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=TEMPERATURE,
            max_tokens=250
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Hệ thống bận, bạn thử lại sau 1 phút nhé."

# -----------------------
# SMART REPLY
# -----------------------
def get_smart_reply(folder, text):
    # 1) exact match
    fast = find_in_json_exact(folder, text)
    if fast:
        return fast

    # 2) ensure dataset loaded
    if folder not in DATABASE:
        DATABASE[folder] = load_dataset_by_folder(folder)
        CORPUS[folder] = build_corpus_from_database(DATABASE[folder])
        EMBEDDINGS[folder] = compute_embeddings_for_page(folder, CORPUS[folder])

    # 3) semantic search
    sims = get_semantic_context(folder, text)
    if not sims:
        return "Bạn muốn hỏi về dịch vụ nào để mình hỗ trợ rõ hơn?"

    # 4) score check
    if sims[0]["score"] < SIMILARITY_THRESHOLD:
        return "Mình chưa rõ bạn hỏi về nội dung nào - bạn mô tả cụ thể hơn giúp mình nhé."

    # 5) filter by dominant file
    files = [s["item"]["file"] for s in sims]
    dominant = max(set(files), key=files.count)
    top_items = [s for s in sims if s["item"]["file"] == dominant]
    if not top_items:
        top_items = sims

    # 6) prompt + llm
    prompt = assemble_system_prompt(folder, text, top_items)
    return ask_llm(prompt, text)

# -----------------------
# FACEBOOK SEND
# -----------------------
def send_text(psid, text):
    try:
        requests.post(FB_SEND_URL, json={
            "recipient": {"id": psid},
            "message": {"text": text}
        })
    except:
        pass

# -----------------------
# WEBHOOK
# -----------------------
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Sai verify token", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    for entry in data.get("entry", []):
        page_id = str(entry.get("id"))
        folder = PAGE_DATASET_MAP.get(page_id)

        if not folder:
            continue

        for evt in entry.get("messaging", []):
            if evt.get("message", {}).get("is_echo"):
                continue
            psid = evt.get("sender", {}).get("id")
            text = evt.get("message", {}).get("text")
            if psid and text:
                reply = get_smart_reply(folder, text)
                send_text(psid, reply)
    return "OK", 200

# -----------------------
# HEALTH
# -----------------------
@app.route("/health")
def health():
    return {"ok": True, "pages": list(DATABASE.keys())}

# -----------------------
# START SERVER
# -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
