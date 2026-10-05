import os
import json
import re
import asyncio
import time
import httpx
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

# ============================================================
# OPENROUTER CONFIG — tembus region lock Google Gemini
# ============================================================
with open('/tmp/or_key.txt') as f:
    OPENROUTER_API_KEY = f.read().strip()
with open('/tmp/or_base_url.txt') as f:
    OPENROUTER_BASE_URL = f.read().strip()

OPENROUTER_MODEL = "google/gemini-3.6-flash"

app = FastAPI(title="ARVI Debate System - OMI 2026")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# DEBATE MODE PROMPTS (7 kepribadian)
# ============================================================
DEBATE_MODES = {
    "santun": "Kamu adalah ARVI mode Santun. Gunakan bahasa Indonesia yang lembut, ramah, meyakinkan, dan empatik. Bahas argumen lawan bicara dengan hormat namun tetap kritis.",
    "agresif": "Kamu adalah ARVI mode Agresif. Potong argumen lawan, sanggah bertubi-tubi, to the point, dan dominan 100% tanpa menggunakan kata-kata kasar.",
    "sokrates": "Kamu adalah ARVI mode Sokrates. Jangan langsung berikan jawaban. Buat pertanyaan-pertanyaan kritis yang memancing pengguna untuk memikirkan kembali asumsi dan logika mereka.",
    "devils_advocate": "Kamu adalah ARVI mode Devil's Advocate. Ambil posisi kontroversial dan lawan argumen pengguna dari sudut pandang yang tidak terpikirkan.",
    "switch_side": "Kamu adalah ARVI mode Switch Side. Tiba-tiba balikkan posisi debatmu secara total di tengah argumen dengan alasan logis.",
    "deep_researcher": "Kamu adalah ARVI mode Deep Researcher. Sertakan data real, jurnal, metodologi ilmiah, dan statistik berbasis bukti.",
    "judge": "Kamu adalah ARVI mode Judge Mode. Bertindaklah sebagai juri netral. Berikan skor logika dari 1-100 dan evaluasi singkat."
}

# ============================================================
# OPENROUTER API CALL
# ============================================================
def call_openrouter(prompt: str, json_mode: bool = False, max_retries: int = 2) -> str:
    """Call Gemini via OpenRouter. json_mode=True → response_format JSON object (for evaluator)."""
    for attempt in range(max_retries):
        try:
            body = {
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7 if not json_mode else 0.3,
                "max_tokens": 1024,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}

            resp = httpx.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=30,
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                if attempt < max_retries - 1:
                    time.sleep(retry_after)
                    continue
                return ""

            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            print(f"[ARVI] OpenRouter error: {e}")
            return ""
        except Exception as e:
            print(f"[ARVI] Unexpected error: {e}")
            return ""
    return ""


# ============================================================
# FAVICON
# ============================================================
@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return JSONResponse(status_code=204, content={})

# ============================================================
# SERVE HTML
# ============================================================
HTML_FILE = Path("/home/ubuntu/arvi.html")

@app.get("/", response_class=HTMLResponse)
def read_root():
    return HTMLResponse(content=HTML_FILE.read_text(encoding="utf-8"))

@app.get("/health")
def health_check():
    return {"status": "OK", "mode_count": len(DEBATE_MODES), "model": OPENROUTER_MODEL}

# ============================================================
# WEBSOCKET — DEBATE ENDPOINT
# ============================================================
@app.websocket("/ws/debate")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[ARVI] Client connected via WebSocket (OpenRouter)")

    try:
        while True:
            raw_data = await websocket.receive_text()

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                data = {"text": raw_data, "mode": "santun"}

            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            user_text = data.get("text", "").strip()
            mode = data.get("mode", "santun").lower()

            if not user_text:
                continue

            # === THINKING INDICATOR ===
            await websocket.send_json({"type": "thinking"})

            loop = asyncio.get_event_loop()

            try:
                # === 1. DEBATE RESPONSE ===
                system_instruction = DEBATE_MODES.get(mode, DEBATE_MODES["santun"])
                debate_prompt = (
                    f"SYSTEM: {system_instruction}\n\n"
                    f"PESAN PENGGUNA: {user_text}\n\n"
                    f"TANGGAPAN ARVI:"
                )
                debate_text = await loop.run_in_executor(
                    None, lambda: call_openrouter(debate_prompt)
                )
                if not debate_text:
                    debate_text = "Maaf, aku lagi error. Coba kirim ulang ya!"

                # Kirim balasan debat dulu
                await websocket.send_json({
                    "type": "response",
                    "agent": "Debate Agent",
                    "message": debate_text,
                    "mode": mode
                })

                # === 2. EVALUATOR (1 call — JSON mode) ===
                eval_prompt = (
                    "Analisis teks argumen pengguna dan berikan output HANYA dalam format JSON valid berikut:\n"
                    "{\n"
                    '  "score": <angka 1-100>,\n'
                    '  "fallacies": ["<nama fallacy 1>", "<nama fallacy 2>"],\n'
                    '  "coach_feedback": "<1 kalimat masukan pelatih>",\n'
                    '  "evidence": ["<fakta/bukti 1>", "<fakta/bukti 2>"]\n'
                    "}\n\n"
                    "Jika tidak ada fallacy, isi array fallacies dengan empty list [].\n"
                    "Jika tidak ada bukti spesifik, isi evidence dengan empty list [].\n"
                    f"TEKS PENGGUNA: {user_text}"
                )

                eval_text = await loop.run_in_executor(
                    None, lambda: call_openrouter(eval_prompt, json_mode=True)
                )

                evaluator_data = {}
                if eval_text:
                    try:
                        evaluator_data = json.loads(eval_text)
                    except json.JSONDecodeError:
                        evaluator_data = {}

                # Kirim evaluasi sebagai pesan terpisah
                await websocket.send_json({
                    "type": "evaluation",
                    "evaluator_data": {
                        "score": evaluator_data.get("score", 0),
                        "fallacies": evaluator_data.get("fallacies", []),
                        "coach_feedback": evaluator_data.get("coach_feedback", ""),
                        "evidence": evaluator_data.get("evidence", [])
                    }
                })

            except Exception as e:
                print(f"[ARVI] Error: {e}")
                await websocket.send_json({
                    "type": "response",
                    "message": f"⚠️ Error: {str(e)[:100]}",
                    "mode": mode
                })

    except WebSocketDisconnect:
        print("[ARVI] Client disconnected")
    except Exception as e:
        print(f"[ARVI] WS error: {e}")