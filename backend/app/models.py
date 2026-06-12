from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class RobotContext(BaseModel):
    robot_type: str
    motors: int = 0
    motor_voltage: Optional[float] = None
    motor_current: Optional[float] = None
    sensors: List[str] = Field(default_factory=list)
    power_source: str
    board_size_mm: Optional[str] = None
    description: str = ""

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    context: Optional[RobotContext] = None

class ChatResponse(BaseModel):
    reply: str
    context: Optional[RobotContext] = None
    follow_up_question: Optional[str] = None

class ComponentChoice(BaseModel):
    name: str
    value: Optional[str] = None
    footprint: Optional[str] = None
    reason: str

class DesignSpec(BaseModel):
    components: List[ComponentChoice]
    nets: List[dict]
    notes: List[str]

class GenerateRequest(BaseModel):
    context: RobotContext
    spec: DesignSpec

class GenerateResponse(BaseModel):
    kicad_sch_path: Optional[str]
    kicad_pcb_path: Optional[str]
    gerber_zip_path: Optional[str]
    bom: List[dict]
    status: str
    errors: List[str]
