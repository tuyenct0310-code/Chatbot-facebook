# app.py - MULTI-PAGE RAG CHATBOT (FULL & MULTI TOKEN)
import os
import json
import time
import random
import requests
import threading
from pathlib import Path
import numpy as np
from tqdm import tqdm
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

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

# MULTI TOKEN FOR MULTI PAGES
PAGE_TOKEN_MAP = {
    "895305580330861": os.environ.get("PAGE_TOKEN_XYZ", ""),   # Page Kiến trúc XYZ
    "847842948414951": os.environ.get("PAGE_TOKEN_CTT", "")    # Page Chatbot CTT
}

# PAGE → FOLDER DATASET
PAGE_DATASET_MAP = {
    "895305580330861": "page_xyz",
    "847842948414951": "page_ctt"
}

DATA_FOLDER_ROOT = Path("data")
EMBEDDINGS_FOLDER = Path("embeddings")

app = Flask(__name__)

# -----------------------
# OpenAI Client
# -----------------------
try:
    client = OpenAI(api_key=OPENAI_KEY)
    print("✅ OpenAI client ready")
except Exception as e:
    print("❌ OpenAI init error:", e)
    client = None

# -----------------------
# GLOBAL STORAGE
# -----------------------
DATABASE = {}
CORPUS = {}
EMBEDDINGS = {}

# -----------------------
# LOAD DATA
# -----------------------
def load_dataset_by_folder(folder):
    folder_path = DATA_FOLDER_ROOT / folder
    db = {}
    if not folder_path.exists():
        print(f"❌ Missing dataset folder: data/{folder}")
        return db

    for f in folder_path.glob("*.json"):
        try:
            with open(f, "r", encoding="utf8") as fh:
                db[f.stem] = json.load(fh)
        except Exception as e:
            print(f"❌ Error loading file {f}: {e}")
    print(f"📂 Loaded data for {folder}: {list(db.keys())}")
    return db

# -----------------------
# CHUNKING
# -----------------------
def text_to_chunks(text, size=CHUNK_SIZE):
    text = text.strip().replace("\n", " ")
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

# -----------------------
# BUILD CORPUS
# -----------------------
def build_corpus_from_database(db):
    corpus = []
    idx = 0

    for file_key, content in db.items():
        for tr in content.get("chatbot_triggers", []):
            kw = " ".join(tr.get("keywords", []))
            resp = tr.get("response", "")
            if isinstance(resp, list):
                resp = " ".join(resp)

            text = f"KEYWORDS: {kw}\nRESPONSE: {resp}"
            for c in text_to_chunks(text):
                corpus.append({"id": f"c{idx}", "file": file_key, "source": "trigger", "text": c})
                idx += 1

        for p in content.get("products", []):
            name = p.get("name", "")
            desc = p.get("description", "")
            if not isinstance(desc, str):
                desc = json.dumps(desc, ensure_ascii=False)

            text = f"PRODUCT: {name}\n{desc}"
            for c in text_to_chunks(text):
                corpus.append({"id": f"c{idx}", "file": file_key, "source": "product", "text": c})
                idx += 1

        for pr in content.get("highlight_projects", []):
            name = pr.get("name", "")
            desc = pr.get("summary", "")
            if not isinstance(desc, str):
                desc = json.dumps(desc, ensure_ascii=False)

            text = f"PROJECT: {name}\n{desc}"
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
# EMBEDDINGS
# -----------------------
def get_embed_path(folder):
    EMBEDDINGS_FOLDER.mkdir(exist_ok=True)
    return EMBEDDINGS_FOLDER / f"{folder}.json"

def compute_embeddings_for_page(folder, corpus, force=False):
    embed_path = get_embed_path(folder)

    if embed_path.exists() and not force:
        try:
            with open(embed_path, "r", encoding="utf8") as fh:
                existing = json.load(fh)
                if len(existing.get("vectors", [])) == len(corpus):
                    print(f"🗄️ Loaded embeddings for {folder}")
                    return existing
                else:
                    print(f"⚠️ Embeddings size mismatch for {folder}, rebuilding...")
        except:
            pass

    print(f"⚙️ Building embeddings for {folder} ({len(corpus)} chunks)...")
    vectors = []
    texts = [c["text"] for c in corpus]
    batch = []
    batch_idx = []

    for i, txt in enumerate(tqdm(texts, desc=f"Embedding {folder}")):
        batch.append(txt)
        batch_idx.append(i)

        if len(batch) >= EMBED_BATCH or i == len(texts) - 1:
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
                for j, out in enumerate(resp.data):
                    idx = batch_idx[j]
                    c = corpus[idx]
                    vectors.append({
                        "id": c["id"],
                        "file": c["file"],
                        "source": c["source"],
                        "text": c["text"],
                        "vec": out.embedding
                    })
            except Exception as e:
                print("❌ Embedding batch error:", e)
                for j, _ in enumerate(batch):
                    idx = batch_idx[j]
                    c = corpus[idx]
                    vectors.append({
                        "id": c["id"],
                        "file": c["file"],
                        "source": c["source"],
                        "text": c["text"],
                        "vec": [0.0]*1536
                    })
            batch = []
            batch_idx = []

    store = {"vectors": vectors, "meta": {"created": time.time()}}
    with open(embed_path, "w", encoding="utf8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)

    print(f"✅ Saved embeddings: {embed_path}")
    return store

# -----------------------
# COSINE SEARCH
# -----------------------
def cosine(a, b):
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)

    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0

    return float(np.dot(a, b) / (na * nb))

def semantic_search(query_vec, store):
    sims = []
    for x in store["vectors"]:
        sims.append({"score": cosine(query_vec, x["vec"]), "item": x})
    sims.sort(key=lambda x: x["score"], reverse=True)
    return sims[:TOP_K]

# -----------------------
# SEMANTIC CONTEXT
# -----------------------
def get_semantic_context(folder, text):
    store = EMBEDDINGS.get(folder, {})
    if not store.get("vectors"):
        print(f"⚠️ Embeddings not ready for {folder}")
        return []

    try:
        resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
        qvec = resp.data[0].embedding
    except Exception as e:
        print("❌ Query embedding error:", e)
        return []

    return semantic_search(qvec, store)

# -----------------------
# FAST JSON EXACT MATCH
# -----------------------
def find_in_json_exact(folder, text):
    t = text.lower()
    db = DATABASE.get(folder, {})

    for file_key, data in db.items():
        for tr in data.get("chatbot_triggers", []):
            for k in tr.get("keywords", []):
                k_lower = k.lower()
                if k_lower and (f" {k_lower} " in f" {t} " or t == k_lower or t.startswith(k_lower + " ") or t.endswith(" " + k_lower)):
                    resp = tr.get("response", "")
                    if isinstance(resp, list):
                        return random.choice(resp)
                    return resp
    return None

# -----------------------
# SYSTEM PROMPT
# -----------------------
def assemble_system_prompt(folder, user_text, top_items):
    files = [i["item"]["file"] for i in top_items]
    dominant = max(set(files), key=files.count)
    persona = {}

    for fk, data in DATABASE.get(folder, {}).items():
        if fk == dominant:
            persona = data.get("persona", {})
            break

    ctx = []
    for x in top_items:
        it = x["item"]
        ctx.append(f"[{it['file']} | {x['score']:.3f}]\n{it['text']}")

    ctx_text = "\n\n---\n\n".join(ctx)

    return f"""
Bạn là trợ lý hỗ trợ khách hàng, trả lời đúng theo dữ liệu cung cấp.
Persona: {json.dumps(persona, ensure_ascii=False)}

--- QUY TẮC ---
1) Chỉ dùng thông tin trong CONTEXT.
2) Nếu không đủ dữ liệu → nói: "Mình chưa có thông tin cụ thể, bạn mô tả rõ hơn giúp mình nhé."
3) Trả lời ngắn gọn 1–3 câu.

--- USER:
{user_text}

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
    except Exception as e:
        print("❌ LLM error:", e)
        return "Hệ thống AI đang bận, vui lòng thử lại sau."

# -----------------------
# SMART REPLY
# -----------------------
def ensure_page_data(folder, force=False):
    if folder not in DATABASE or force:
        DATABASE[folder] = load_dataset_by_folder(folder)
        CORPUS[folder] = build_corpus_from_database(DATABASE[folder])
        EMBEDDINGS[folder] = compute_embeddings_for_page(folder, CORPUS[folder], force=force)

def get_smart_reply(folder, text):
    fast = find_in_json_exact(folder, text)
    if fast:
        return fast

    ensure_page_data(folder)

    sims = get_semantic_context(folder, text)
    if not sims:
        return "Bạn muốn hỏi về nội dung nào để mình hỗ trợ rõ hơn?"

    if sims[0]["score"] < SIMILARITY_THRESHOLD:
        return "Mình chưa rõ bạn muốn hỏi gì – bạn mô tả chi tiết hơn nhé?"

    files = [s["item"]["file"] for s in sims]
    dominant = max(set(files), key=files.count)

    top_items = [s for s in sims if s["item"]["file"] == dominant]
    if not top_items:
        top_items = sims

    prompt = assemble_system_prompt(folder, text, top_items)
    return ask_llm(prompt, text)

# -----------------------
# FACEBOOK SEND (NEW MULTI TOKEN)
# -----------------------
def send_text(page_id, psid, text):
    token = PAGE_TOKEN_MAP.get(page_id)

    if not token:
        print("❌ Missing token for page:", page_id)
        return

    url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"

    payload = {
        "recipient": {"id": psid},
        "message": {"text": text}
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        print("📨 FB Send:", r.status_code, r.text)
    except Exception as e:
        print("❌ FB send error:", e)

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
            print("⚠️ Page không được cấu hình:", page_id)
            continue

        for evt in entry.get("messaging", []):
            if evt.get("message", {}).get("is_echo"):
                continue

            psid = evt.get("sender", {}).get("id")
            text = evt.get("message", {}).get("text")

            if psid and text:
                print(f"🌐 [{folder}] User {psid}: {text}")

                reply = get_smart_reply(folder, text)

                threading.Thread(
                    target=send_text,
                    args=(page_id, psid, reply)
                ).start()

    return "OK", 200

# -----------------------
# HEALTH CHECK
# -----------------------
@app.route("/health")
def health():
    result = {}
    for page_id, folder in PAGE_DATASET_MAP.items():
        result[page_id] = {
            "folder": folder,
            "ready": len(EMBEDDINGS.get(folder, {}).get("vectors", [])) > 0
        }
    return jsonify(ok=True, pages=result)

# -----------------------
# STARTUP BUILD
# -----------------------
def initial_background_build():
    for folder in set(PAGE_DATASET_MAP.values()):
        threading.Thread(
            target=lambda fn=folder: ensure_page_data(fn, force=False),
            daemon=True
        ).start()

if __name__ == "__main__":
    initial_background_build()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
