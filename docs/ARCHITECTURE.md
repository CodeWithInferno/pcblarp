# PCBlarp Architecture

## Flow

1. User types robot description in chat
2. Backend LLM (Nebius) asks follow-ups and extracts `RobotContext`
3. Backend generates `DesignSpec` (component list + nets)
4. `kicad_generator.py` writes real `.kicad_sch` and `.kicad_pcb` files
5. Frontend shows schematic + interactive 3D PCB preview

## Important design choice

The LLM **does not** write KiCad files directly. It outputs structured JSON. Python code writes the precise S-expressions. This avoids LLM syntax errors.

## Files

- `frontend/src/components/ChatWizard.tsx` — Mahek
- `backend/app/llm_client.py` — Kanha
- `backend/app/kicad_generator.py` — Manay
- `frontend/src/components/PCBViewer3D.tsx` + `backend/app/pcb_renderer.py` — Pratham
