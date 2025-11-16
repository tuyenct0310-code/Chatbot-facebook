# app.py - MULTI-PAGE RAG CHATBOT (FULL & TỐI ƯU)
import os
import json
import time
import random
import requests
import threading
from pathlib import Path
# Cần import numpy và tqdm để chạy các hàm tính toán và hiển thị tiến trình
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

PAGE_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

# -----------------------
# PAGE → DATA FOLDER MAPPING
# -----------------------
PAGE_DATASET_MAP = {
    "895305580330861": "page_xyz",     # Kiến trúc XYZ
    "847842948414951": "page_ctt"      # Chatbot CTT
}

DATA_FOLDER_ROOT = Path("data")
EMBEDDINGS_FOLDER = Path("embeddings")

app = Flask(__name__)

# -----------------------
# OpenAI
# -----------------------
try:
    client = OpenAI(api_key=OPENAI_KEY)
    print("✅ OpenAI client ready")
except Exception as e:
    print("❌ OpenAI init error:", e)
    client = None

# -----------------------
# STORAGE
# -----------------------
# DATABASE[folder_name] = { file_key: content_dict, ... }
DATABASE = {}
# CORPUS[folder_name] = [ chunk_dict, ... ]
CORPUS = {}
# EMBEDDINGS[folder_name] = { "vectors": [...], "meta": {...} }
EMBEDDINGS = {}

# -----------------------
# LOAD DATASET
# -----------------------
def load_dataset_by_folder(folder):
    folder_path = DATA_FOLDER_ROOT / folder
    db = {}
    if not folder_path.exists():
        print(f"❌ data/{folder} folder missing")
        return db
    for f in folder_path.glob("*.json"):
        try:
            with open(f, "r", encoding="utf8") as fh:
                db[f.stem] = json.load(fh)
        except Exception as e:
            print(f"❌ Load fail {f}: {e}")
            pass
    print(f"📂 Loaded data for '{folder}': {list(db.keys())}")
    return db

# -----------------------
# CHUNKING + CORPUS
# -----------------------
def text_to_chunks(text, size=CHUNK_SIZE):
    text = text.strip().replace("\n", " ") # Dùng "\n" thay cho khoảng trắng
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

def build_corpus_from_database(db):
    corpus = []
    idx = 0
    for file_key, content in db.items():
        for tr in content.get("chatbot_triggers", []):
            kw = " ".join(tr.get("keywords", []))
            resp = tr.get("response", "")
            if isinstance(resp, list): resp = " ".join(resp)
            # Dùng \n thay cho khoảng trắng
            text = f"KEYWORDS: {kw}\nRESPONSE: {resp}"
            for c in text_to_chunks(text):
                corpus.append({"id": f"c{idx}", "file": file_key, "source": "trigger", "text": c})
                idx += 1

        for p in content.get("products", []):
            name = p.get("name", "")
            desc = p.get("description", "")
            if not isinstance(desc, str): desc = json.dumps(desc, ensure_ascii=False)
            text = f"PRODUCT: {name}\n{desc}"
            for c in text_to_chunks(text):
                corpus.append({"id": f"c{idx}", "file": file_key, "source": "product", "text": c})
                idx += 1

        for pr in content.get("highlight_projects", []):
            name = pr.get("name", "")
            desc = pr.get("summary", "")
            if not isinstance(desc, str): desc = json.dumps(desc, ensure_ascii=False)
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
# EMBEDDING
# -----------------------
def get_embed_path(folder):
    EMBEDDINGS_FOLDER.mkdir(exist_ok=True) # Đảm bảo thư mục embeddings tồn tại
    return EMBEDDINGS_FOLDER / f"{folder}.json"

def compute_embeddings_for_page(folder, corpus, force=False):
    embed_path = get_embed_path(folder)

    if embed_path.exists() and not force:
        try:
            with open(embed_path, "r", encoding="utf8") as fh:
                existing = json.load(fh)
                if len(existing.get("vectors", [])) == len(corpus):
                    print(f"🗄️ Load embeddings for '{folder}' from disk.")
                    return existing
                else:
                    print(f"⚠️ Embedding count mismatch for '{folder}'. Rebuilding.")
        except Exception as e:
            print(f"❌ Load embedding error for '{folder}': {e}. Rebuilding.")
            pass # Chuyển sang build mới

    print(f"⚙️ Creating embeddings for '{folder}' ({len(corpus)} chunks)...")

    vectors = []
    texts = [c["text"] for c in corpus]
    batch, batch_idx = [], []

    for i, txt in enumerate(tqdm(texts, desc=f"Embedding {folder}")): # Dùng tqdm để hiển thị tiến trình
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
            except Exception as e:
                print(f"❌ Embedding API error (batch {i//EMBED_BATCH}):", e)
                for j, _ in enumerate(batch):
                    idx = batch_idx[j]
                    c = corpus[idx]
                    vectors.append({
                        "id": c["id"], "file": c["file"], "source": c["source"],
                        "text": c["text"], "vec": [0.0]*1536 # Kích thước 1536 cho text-embedding-3-large
                    })
            batch, batch_idx = [], []

    store = {"vectors": vectors, "meta": {"created": time.time()}}
    with open(embed_path, "w", encoding="utf8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)
    print(f"✅ Embeddings saved: {embed_path}")
    return store

# -----------------------
# SIMILARITY
# -----------------------
def cosine(a, b):
    # Đảm bảo a, b là numpy array
    a = np.array(a, dtype=float) 
    b = np.array(b, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0: return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

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
    store = EMBEDDINGS.get(folder, {})
    if not store or not store.get("vectors"):
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
# FAST JSON MATCH
# -----------------------
def find_in_json_exact(folder, text):
    db = DATABASE.get(folder, {})
    t = text.lower()
    for file_key, data in db.items():
        for tr in data.get("chatbot_triggers", []):
            for k in tr.get("keywords", []):
                # Kiểm tra match token nghiêm ngặt hơn
                k_lower = k.lower()
                if k_lower and (f" {k_lower} " in f" {t} " or t.startswith(k_lower + " ") or t.endswith(" " + k_lower) or t == k_lower):
                    resp = tr.get("response", "")
                    if isinstance(resp, list): return random.choice(resp)
                    return random.choice(resp.splitlines()) # Chọn ngẫu nhiên 1 dòng nếu có nhiều dòng
    return None

# -----------------------
# SYSTEM PROMPT
# -----------------------
def assemble_system_prompt(folder, user_text, top_items):
    files = [i["item"]["file"] for i in top_items]
    dominant = max(set(files), key=files.count)
    persona = {}

    # Lấy persona từ file dominant
    for file_key, data in DATABASE.get(folder, {}).items():
        if file_key == dominant:
            persona = data.get("persona", {})
            break

    ctx = []
    for x in top_items:
        it = x["item"]
        ctx.append(f"[file:{it['file']} score:{x['score']:.3f}]\n{it['text']}")

    ctx_text = "\n\n---\n\n".join(ctx)

    return f"""
Bạn là trợ lý hỗ trợ khách hàng, trả lời dựa trên đúng dữ liệu cung cấp.
Persona: {json.dumps(persona, ensure_ascii=False)}

--- QUY TẮC RẤT CHẶT ---
1) Chỉ trả lời dựa trên phần CONTEXT dưới đây. Không thêm, không suy diễn.
2) Nếu câu trả lời không thể rút ra từ CONTEXT → Trả lời: "Mình chưa có thông tin cụ thể, bạn cho mình biết rõ hơn được không?"
3) Trả lời ngắn gọn 1-3 câu, trực tiếp.

--- USER:
"{user_text}"

--- CONTEXT (Chỉ dùng phần này):
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
        print("❌ OpenAI chat error:", e)
        return "Hệ thống AI đang bận, bạn thử lại sau 1 phút nhé."

# -----------------------
# SMART REPLY
# -----------------------
def ensure_page_data(folder, force=False):
    """Đảm bảo data, corpus và embeddings đã được tải/tạo cho folder."""
    if folder not in DATABASE or force:
        DATABASE[folder] = load_dataset_by_folder(folder)
        CORPUS[folder] = build_corpus_from_database(DATABASE[folder])
        EMBEDDINGS[folder] = compute_embeddings_for_page(folder, CORPUS[folder], force=force)

def get_smart_reply(folder, text):
    # 1) exact match
    fast = find_in_json_exact(folder, text)
    if fast:
        return fast

    # 2) ensure dataset loaded (chạy nền lần đầu)
    ensure_page_data(folder)

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
        top_items = sims # Fallback nếu dominant file không có items

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
        }, timeout=15)
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
            print(f"⚠️ Page ID {page_id} chưa được cấu hình. Bỏ qua.")
            continue

        for evt in entry.get("messaging", []):
            if evt.get("message", {}).get("is_echo"):
                continue
            psid = evt.get("sender", {}).get("id")
            text = evt.get("message", {}).get("text")
            
            if psid and text:
                print(f"🌐 Page:{folder} | 👤 {psid} -> {text}")
                reply = get_smart_reply(folder, text)
                print(f"🤖 reply ({folder}):", reply)
                # Dùng threading để gửi tin nhắn không block luồng xử lý webhook
                threading.Thread(target=send_text, args=(psid, reply)).start()
                
    return "OK", 200

# -----------------------
# HEALTH
# -----------------------
@app.route("/health")
def health():
    status = {}
    for page_id, folder_name in PAGE_DATASET_MAP.items():
        embed_count = len(EMBEDDINGS.get(folder_name, {}).get("vectors", []))
        data_files = list(DATABASE.get(folder_name, {}).keys())
        status[page_id] = {
            "folder": folder_name,
            "data_files": data_files,
            "embed_count": embed_count,
            "ready": embed_count > 0
        }
    return jsonify(ok=True, pages=status)

# -----------------------
# START SERVER (Khởi động Build nền)
# -----------------------
def initial_background_build():
    """Khởi động quá trình tải data và build embeddings nền cho tất cả Pages."""
    print("🚀 Khởi động quá trình build embeddings nền cho tất cả Pages...")
    for folder_name in set(PAGE_DATASET_MAP.values()):
        # Tải/Build nền, không force
        threading.Thread(
            target=lambda fn=folder_name: ensure_page_data(fn, force=False),
            daemon=True
        ).start()

if __name__ == "__main__":
    initial_background_build()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
