import os
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.models import ChatRequest, ChatResponse, GenerateRequest, GenerateResponse
from app.llm_client import ask_llm, extract_context, build_component_prompt
from app.kicad_generator import generate_kicad_project

api_router = APIRouter()

SESSIONS = {}

@api_router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        reply = ask_llm(req.messages)
        return ChatResponse(
            reply=reply,
            context=extract_context(req.messages) if req.context is None else req.context,
            follow_up_question=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/design/spec")
def design_spec(context: dict):
    """Return a structured component/netlist spec from context."""
    prompt = build_component_prompt(context)
    # In a full version this calls LLM and parses JSON.
    # For scaffolding, return a mock spec.
    return {
        "prompt": prompt,
        "components": [
            {"name": "BTS7960", "role": "motor_driver", "count": 2},
            {"name": "Arduino UNO Q", "role": "mcu", "count": 1},
            {"name": "MPU6050", "role": "imu", "count": 1},
        ],
        "nets": [
            {"name": "VMOT", "voltage": 12.0},
            {"name": "VLOGIC", "voltage": 5.0},
            {"name": "GND", "type": "ground"},
        ],
    }

@api_router.post("/design/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    session_id = str(uuid.uuid4())[:8]
    out_dir = os.path.join("generated", session_id)
    os.makedirs(out_dir, exist_ok=True)

    try:
        result = generate_kicad_project(req.context, req.spec, out_dir)
        return GenerateResponse(
            kicad_sch_path=result.get("sch"),
            kicad_pcb_path=result.get("pcb"),
            gerber_zip_path=result.get("gerbers"),
            bom=result.get("bom", []),
            status="generated",
            errors=[],
        )
    except Exception as e:
        return GenerateResponse(
            kicad_sch_path=None,
            kicad_pcb_path=None,
            gerber_zip_path=None,
            bom=[],
            status="error",
            errors=[str(e)],
        )

@api_router.get("/files/{session_id}/{filename}")
def get_file(session_id: str, filename: str):
    path = os.path.join("generated", session_id, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)
