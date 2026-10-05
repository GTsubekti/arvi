# ARVI — Argumentation & Reasoning Virtual Intelligence

**Multi-Agent AI Debate System untuk Meningkatkan Penalaran Kritis Siswa**

> OMI 2026 — MAN 5 Kediri

## Struktur

| Path | Isi |
|------|-----|
| `index.html` | Frontend AI Debate (deploy ke Vercel) |
| `backend/` | Backend FastAPI + WebSocket (jalan di VPS) |

## Deploy

### Frontend (Vercel)
1. Fork/clone repo ini
2. Import ke [Vercel](https://vercel.com/new)
3. Set Framework = Static
4. Deploy → domain `.vercel.app` otomatis

### Backend (VPS)
```bash
cd backend
pip install -r requirements.txt
uvicorn arvi_backend:app --host 0.0.0.0 --port 8000
```

Pastikan file `/tmp/or_key.txt` berisi OpenRouter API key.
Pastikan file `/tmp/or_base_url.txt` berisi `https://openrouter.ai/api/v1`.

## 7 Mode Debat
Santun · Agresif · Sokrates · Devil's Advocate · Switch Side · Deep Researcher · Judge