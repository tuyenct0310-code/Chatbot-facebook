# app.py
import os
import json
import math
import time
import random
import requests
import threading
from pathlib import Path
from tqdm import tqdm
import numpy as np
from flask import Flask, request, jsonify
from openai import OpenAI

# -----------------------
#  CONFIG
# -----------------------
EMBED_MODEL = "text-embedding-3-large"
CHAT_MODEL = "gpt-4o-mini"
EMBED_BATCH = 16  # nếu có nhiều text, chia batch
EMBED_FILE = "embeddings_store.json"
CHUNK_SIZE = 400  # ký tự trên chunk (tùy chỉnh)
SIMILARITY_THRESHOLD = 0.72  # nếu score thấp hơn -> hỏi lại
TOP_K = 5
TEMPERATURE = 0.12

PAGE_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

FB_SEND_URL = f"https://graph.facebook.com/v19.0/me/messages?access_token={PAGE_TOKEN}"

app = Flask(__name__)

# -----------------------
#  OpenAI client
# -----------------------
try:
    client = OpenAI(api_key=OPENAI_KEY)
    print("✅ OpenAI client ready")
except Exception as e:
    print("❌ OpenAI init error:", e)
    client = None

# -----------------------
#  Load JSON dataset
# -----------------------
DATA_FOLDER = Path("data")
FILE_PRIORITY_ORDER = [
    "quangcao_chatbot_ctt",
    "kientruc_xyz",
    "oc_ngon_18"
]

def load_all_data(folder=DATA_FOLDER):
    db = {}
    if not folder.exists():
        print("❌ data/ folder missing")
        return db
    for f in folder.glob("*.json"):
        try:
            key = f.stem
            with open(f, "r", encoding="utf8") as fh:
                db[key] = json.load(fh)
        except Exception as e:
            print("❌ load fail", f, e)
    print("📂 Loaded:", list(db.keys()))
    return db

DATABASE = load_all_data()

# -----------------------
#  Chunking & Indexing
# -----------------------
def text_to_chunks(text, size=CHUNK_SIZE):
    text = text.strip()
    if not text:
        return []
    # chia theo câu gần đúng rồi ghép cho đủ chunk
    parts = text.replace("\n", " ").split(". ")
    chunks = []
    cur = ""
    for p in parts:
        if len(cur) + len(p) + 2 <= size:
            cur = (cur + ". " + p).strip(" .")
        else:
            if cur:
                chunks.append(cur.strip())
            cur = p
    if cur:
        chunks.append(cur.strip())
    # nếu vẫn có chunk quá dài thì cắt trực tiếp
    final = []
    for c in chunks:
        if len(c) <= size:
            final.append(c)
        else:
            for i in range(0, len(c), size):
                final.append(c[i:i+size])
    return final

def build_corpus_from_database(db):
    """
    Tạo danh sách chunk dict:
    { "id": str, "file": file_key, "source": "trigger|product|project|persona",
      "text": chunk_text }
    """
    corpus = []
    idx = 0
    for file_key, content in db.items():
        # triggers: thường chứa responses and keywords
        for tr in content.get("chatbot_triggers", []):
            # include keywords + response text
            keywords = " ".join(tr.get("keywords", []))
            resp = tr.get("response", "")
            if isinstance(resp, list):
                resp = " ".join(resp)
            text = f"KEYWORDS: {keywords}\nRESPONSE: {resp}"
            for chunk in text_to_chunks(text):
                corpus.append({
                    "id": f"c_{idx}",
                    "file": file_key,
                    "source": "trigger",
                    "text": chunk
                })
                idx += 1

        # products
        for p in content.get("products", []):
            name = p.get("name", "")
            desc = p.get("description", "") if isinstance(p.get("description", ""), str) else json.dumps(p.get("description", ""))
            text = f"PRODUCT: {name}\n{desc}"
            for chunk in text_to_chunks(text):
                corpus.append({
                    "id": f"c_{idx}",
                    "file": file_key,
                    "source": "product",
                    "text": chunk
                })
                idx += 1

        # projects
        for pr in content.get("highlight_projects", []):
            name = pr.get("name", "")
            desc = pr.get("summary", "") if isinstance(pr.get("summary", ""), str) else json.dumps(pr.get("summary", ""))
            text = f"PROJECT: {name}\n{desc}"
            for chunk in text_to_chunks(text):
                corpus.append({
                    "id": f"c_{idx}",
                    "file": file_key,
                    "source": "project",
                    "text": chunk
                })
                idx += 1

        # persona (short)
        persona = content.get("persona", {})
        if persona:
            text = f"PERSONA: {persona.get('role','')}. {persona.get('tone','')}. Goal: {persona.get('goal','')}"
            for chunk in text_to_chunks(text):
                corpus.append({
                    "id": f"c_{idx}",
                    "file": file_key,
                    "source": "persona",
                    "text": chunk
                })
                idx += 1

    return corpus

# -----------------------
#  Embedding store (disk)
# -----------------------
def load_embeddings(path=EMBED_FILE):
    if not Path(path).exists():
        return None
    with open(path, "r", encoding="utf8") as fh:
        return json.load(fh)

def save_embeddings(store, path=EMBED_FILE):
    with open(path, "w", encoding="utf8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)

def compute_embeddings_for_corpus(corpus, force_rebuild=False):
    """
    corpus: list of chunk dicts
    returns store: {"vectors": [{"id":..., "vec":[...], "file":..., "source":..., "text":...}], "meta": {...}}
    """
    existing = load_embeddings()
    if existing and not force_rebuild:
        # quick sanity: if size matches corpus length use it
        if len(existing.get("vectors", [])) == len(corpus):
            print("🗄️ Load embeddings from disk")
            return existing
        else:
            print("⚠️ Embedding count mismatch. Rebuilding.")

    print("⚙️ Creating embeddings for corpus (this may take a while)...")
    vectors = []
    texts = [c["text"] for c in corpus]
    batch = []
    batch_idx = []
    for i, txt in enumerate(tqdm(texts, desc="chunks")):
        batch.append(txt)
        batch_idx.append(i)
        if len(batch) >= EMBED_BATCH or i == len(texts) - 1:
            # call embeddings
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
                # SDK response assumed resp.data[*].embedding
                for j, out in enumerate(resp.data):
                    emb = out.embedding
                    idx = batch_idx[j]
                    c = corpus[idx]
                    vectors.append({
                        "id": c["id"],
                        "file": c["file"],
                        "source": c["source"],
                        "text": c["text"],
                        "vec": emb
                    })
            except Exception as e:
                print("❌ Embedding API error:", e)
                # fallback: zero vector (avoid crash) but mark low similarity
                for j, _ in enumerate(batch):
                    idx = batch_idx[j]
                    c = corpus[idx]
                    vectors.append({
                        "id": c["id"],
                        "file": c["file"],
                        "source": c["source"],
                        "text": c["text"],
                        "vec": [0.0]*1536  # size for text-embedding-3-large; if fails it's okay
                    })
            batch = []
            batch_idx = []

    store = {"vectors": vectors, "meta": {"created_at": time.time(), "n": len(vectors)}}
    save_embeddings(store)
    print("✅ Embeddings saved:", EMBED_FILE)
    return store

# -----------------------
#  Similarity utils
# -----------------------
def cosine(a, b):
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def semantic_search(query_vec, store, top_k=TOP_K):
    sims = []
    for item in store["vectors"]:
        s = cosine(query_vec, item["vec"])
        sims.append({"score": s, "item": item})
    sims_sorted = sorted(sims, key=lambda x: x["score"], reverse=True)
    return sims_sorted[:top_k]

# -----------------------
#  RAG pipeline
# -----------------------
EMBED_STORE = None
CORPUS = None

def ensure_embeddings(force=False):
    global EMBED_STORE, CORPUS
    if EMBED_STORE and CORPUS and not force:
        return
    CORPUS = build_corpus_from_database(DATABASE)
    EMBED_STORE = compute_embeddings_for_corpus(CORPUS, force_rebuild=force)

# build embeddings on startup in background to not block webhook
def background_build():
    try:
        ensure_embeddings(force=False)
    except Exception as e:
        print("⚠️ background build error:", e)

threading.Thread(target=background_build, daemon=True).start()

def get_semantic_context(user_text, top_k=TOP_K):
    # 1) embed query
    try:
        resp = client.embeddings.create(model=EMBED_MODEL, input=[user_text])
        qvec = resp.data[0].embedding
    except Exception as e:
        print("❌ Query embedding error:", e)
        return []

    # 2) search
    store = EMBED_STORE
    if not store:
        print("⚠️ No embed store")
        return []

    sims = semantic_search(qvec, store, top_k=top_k)
    return sims

# -----------------------
#  Strict rules + persona + call OpenAI
# -----------------------
def assemble_system_prompt(user_text, top_items):
    # top_items: list of {"score","item"}
    # identify dominant file (most frequent)
    files = [it["item"]["file"] for it in top_items]
    dominant = None
    if files:
        dominant = max(set(files), key=lambda x: files.count(x))
    # persona from dominant file if possible
    persona = {}
    for key in FILE_PRIORITY_ORDER:
        persona = DATABASE.get(dominant, {}).get("persona", {}) if dominant else {}
        break

    # build context text limited to top_items
    pieces = []
    for s in top_items:
        item = s["item"]
        pieces.append(f"[source:{item['source']} file:{item['file']} score:{s['score']:.3f}]\n{item['text']}")

    context_text = "\n\n---\n\n".join(pieces) if pieces else ""

    system_prompt = f"""
Bạn là trợ lý hỗ trợ khách hàng cho dịch vụ của khách hàng. 
Persona (nếu có): {json.dumps(persona, ensure_ascii=False)}.

--- NGUYÊN TẮC RẤT CHẶT ---
1) Chỉ được phép trả lời dựa trên phần CONTEXT dưới đây. Không thêm, không suy diễn, không đoán.
2) Nếu câu trả lời không thể rút ra từ CONTEXT → Trả lời: "Mình chưa có thông tin cụ thể, bạn cho mình biết rõ bạn đang hỏi về dịch vụ nào hoặc chi tiết hơn được không?"
3) Không được lấy thông tin từ file khác nếu dominant file đã được xác định.
4) Trả lời ngắn gọn 1–3 câu, trực tiếp, không marketing thổi phồng.
5) Nếu khách hỏi nhiều dịch vụ trong 1 câu -> yêu cầu họ nêu rõ 1 dịch vụ một lần.

--- CÂU HỎI KHÁCH ---
\"{user_text}\"

--- CONTEXT (chỉ dùng phần này) ---
{context_text}

--- HƯỚNG DẪN KĨ THUẬT ---
- Nếu phần context chỉ chứa KEYWORD mà không có response cụ thể thì coi như không đủ dữ liệu.
- Nếu độ tương đồng của top result < {SIMILARITY_THRESHOLD} thì KHÔNG gọi OpenAI mà hỏi lại khách.
"""
    return system_prompt

def call_openai_chat(system_prompt, user_text):
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        temperature=TEMPERATURE,
        max_tokens=300
    )
    return resp.choices[0].message.content.strip()

# -----------------------
#  Fast JSON exact match (keeps legacy behavior)
# -----------------------
def find_in_json_exact(text):
    if not DATABASE:
        return None
    t = text.lower()
    for file_key in FILE_PRIORITY_ORDER:
        data = DATABASE.get(file_key)
        if not data:
            continue
        for tr in data.get("chatbot_triggers", []):
            keywords = [k.lower() for k in tr.get("keywords", [])]
            # stricter: match full keyword token in text
            for k in keywords:
                if k and ((" " + k + " ") in (" " + t + " ") or t.startswith(k + " ") or t.endswith(" " + k)):
                    resp = tr.get("response", "")
                    if isinstance(resp, list):
                        return random.choice(resp)
                    return random.choice(resp.splitlines())
    return None

# -----------------------
#  Main reply pipeline
# -----------------------
def get_smart_reply(user_text):
    # 1) try exact json responses first
    fast = find_in_json_exact(user_text)
    if fast:
        return fast

    # 2) ensure embeddings ready
    ensure_embeddings(force=False)

    # 3) semantic search
    sims = get_semantic_context(user_text, top_k=TOP_K)
    if not sims:
        return "Bạn đang hỏi về vấn đề nào vậy? Cho mình biết dịch vụ cụ thể để hỗ trợ nhé."

    # 4) check top score vs threshold
    top_score = sims[0]["score"]
    if top_score < SIMILARITY_THRESHOLD:
        # don't call OpenAI: ask clarifying question
        return "Mình chưa thấy thông tin rõ ràng — bạn đang hỏi về dịch vụ nào trong số dịch vụ của bên mình? (ví dụ: chatbot / thiết kế / ốc) "

    # 5) filter to items belonging to dominant file to avoid cross-file mix
    files = [it["item"]["file"] for it in sims]
    dominant = max(set(files), key=lambda x: files.count(x))
    filtered = [s for s in sims if s["item"]["file"] == dominant]
    # if filtered empty fallback to sims
    top_items = filtered if filtered else sims

    # 6) assemble strict system prompt with only these top_items
    system_prompt = assemble_system_prompt(user_text, top_items)
    try:
        answer = call_openai_chat(system_prompt, user_text)
        # final safety: if answer contains phrases outside context? (simple guard)
        # if answer too generic or says "I don't know" -> ask user to clarify
        low_conf_phrases = ["i don't know", "i'm not sure", "không có thông tin", "mình chưa biết"]
        if any(p in answer.lower() for p in low_conf_phrases):
            return "Mình chưa có thông tin cụ thể, bạn cho mình biết dịch vụ hoặc chi tiết hơn được không?"
        return answer
    except Exception as e:
        print("❌ OpenAI chat error:", e)
        return "Hệ thống AI đang bận, bạn thử lại sau 1 phút nhé."

# -----------------------
#  Facebook send helper
# -----------------------
def send_text(psid, text):
    if not psid or not text:
        return
    try:
        requests.post(FB_SEND_URL, json={
            "recipient": {"id": psid},
            "message": {"text": text}
        }, timeout=15)
    except Exception as e:
        print("❌ FB send error:", e)

# -----------------------
#  Webhook
# -----------------------
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
            text = evt.get("message", {}).get("text")
            if psid and text:
                print(f"👤 {psid} -> {text}")
                reply = get_smart_reply(text)
                print("🤖 reply:", reply)
                send_text(psid, reply)
    return "OK", 200

@app.route("/health")
def health():
    return jsonify(
        ok=True,
        num_files=len(DATABASE),
        files=list(DATABASE.keys()),
        embed_count=len(EMBED_STORE["vectors"]) if EMBED_STORE else 0
    )
# ======================================================
#  ENDPOINT REBUILD EMBEDDINGS (tự động xóa + build lại)
# ======================================================
@app.route("/rebuild-embed", methods=["GET"])
def rebuild_embed():
    try:
        # Xoá file embeddings_store.json nếu tồn tại
        if os.path.exists("embeddings_store.json"):
            os.remove("embeddings_store.json")
            msg = "Đã xóa embeddings_store.json. Bắt đầu build lại..."
            print("⚠️", msg)
        else:
            msg = "Không thấy embeddings_store.json. Sẽ build mới."

        # Build lại (force = True)
        ensure_embeddings(force=True)

        return {
            "ok": True,
            "message": "Rebuild embeddings thành công.",
            "detail": msg
        }

    except Exception as e:
        print("❌ Lỗi rebuild embeddings:", e)
        return {"ok": False, "error": str(e)}, 500

if __name__ == "__main__":
    # force-build embeddings once before serving (optional)
    # ensure_embeddings(force=True)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))


