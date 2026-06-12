# PCBlarp 🤖⚡

AI-powered PCB design agent for robots. Built for the Nebius hackathon.

Describe your robot in plain English, answer a few follow-up questions, and get a manufacturable KiCad schematic + PCB layout with an interactive 3D preview.

![stack](https://img.shields.io/badge/stack-React%20%2B%20FastAPI%20%2B%20Nebius-blue)
![license](https://img.shields.io/badge/license-MIT-green)

---

## ✨ What it does

1. **Chat intake** — tell the agent about your robot (motors, sensors, power, size).
2. **Smart follow-ups** — the LLM fills in missing details and picks components.
3. **KiCad generation** — produces real `.kicad_sch` and `.kicad_pcb` files.
4. **3D preview** — view the board in the browser, powered by Three.js and Nebius.
5. **Export** — download Gerbers and BOM for fabrication.

---

## 🚀 Quick start

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env    # fill in your Nebius API key
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp ../.env.example .env    # fill in VITE_API_URL if not using the proxy
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

---

## 🏗️ Architecture

```
User chat → LLM on Nebius → structured RobotContext + DesignSpec
                                    ↓
                    Python KiCad generator writes .kicad_sch / .kicad_pcb
                                    ↓
            Frontend shows schematic + 3D PCB preview + download Gerbers/BOM
```

The LLM **never writes KiCad files directly**. It outputs structured JSON; Python code generates the precise S-expressions. This avoids syntax errors and hallucinated footprints.

---

## 👥 Team

| Who | Focus |
|-----|-------|
| Mahek | Chat wizard UI (`frontend/src/components/ChatWizard.tsx`) |
| Kanha | LLM prompts + component selection (`backend/app/llm_client.py`) |
| Manay | KiCad file generation (`backend/app/kicad_generator.py`) |
| Pratham | 3D viewer + full-stack integration (`frontend/src/components/PCBViewer3D.tsx`) |

---

## 🔑 Environment variables

```bash
NEBIUS_API_KEY=your_nebius_key
NEBIUS_BASE_URL=https://api.studio.nebius.ai/v1
BACKEND_PORT=8000
CORS_ORIGINS=http://localhost:5173
VITE_API_URL=http://localhost:8000
```

---

## 📁 Project structure

```
pcblarp/
├── frontend/           # React + Vite + TypeScript + Tailwind
├── backend/            # FastAPI Python server
├── shared/schema.ts    # Shared frontend/backend types
├── docs/               # Architecture notes
└── README.md
```

---

## 🛣️ Roadmap / TODO

- [ ] Real KiCad S-expression generation for motor driver boards
- [ ] LLM-powered component selection from LCSC catalog
- [ ] DRC validation with `kicad-cli`
- [ ] Gerber + drill export
- [ ] Nebius GPU-rendered 3D board preview
- [ ] Support for 2/4/6-layer stackups

---

## 🙏 Acknowledgements

Built with [KiCad](https://www.kicad.org/), inspired by [boardsmith](https://github.com/ForestHubAI/boardsmith) and [kicad-tools](https://github.com/rjwalters/kicad-tools).
