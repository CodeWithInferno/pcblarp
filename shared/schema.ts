// Shared TypeScript types for frontend ↔ backend contract.
// Keep this file in sync with backend/app/models.py

export interface RobotContext {
  robot_type: string
  motors: number
  motor_voltage?: number
  motor_current?: number
  sensors: string[]
  power_source: string
  board_size_mm?: string
  description: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface ChatRequest {
  messages: ChatMessage[]
  context?: RobotContext
}

export interface ChatResponse {
  reply: string
  context?: RobotContext
  follow_up_question?: string
}

export interface ComponentChoice {
  name: string
  value?: string
  footprint?: string
  reason: string
}

export interface DesignSpec {
  components: ComponentChoice[]
  nets: Record<string, unknown>[]
  notes: string[]
}

export interface GenerateRequest {
  context: RobotContext
  spec: DesignSpec
}

export interface GenerateResponse {
  kicad_sch_path?: string
  kicad_pcb_path?: string
  gerber_zip_path?: string
  bom: Record<string, unknown>[]
  status: string
  errors: string[]
}
