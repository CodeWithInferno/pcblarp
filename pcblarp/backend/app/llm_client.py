import os
from openai import OpenAI

_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("NEBIUS_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("NEBIUS_BASE_URL", "https://api.studio.nebius.ai/v1")
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client

def ask_llm(messages: list, model: str = None) -> str:
    client = get_client()
    model = model or os.getenv("LLM_MODEL", "meta-llama/Meta-Llama-3.1-70B-Instruct")
    response = client.chat.completions.create(
        model=model,
        messages=[m.model_dump() for m in messages],
        temperature=0.3,
        max_tokens=1024,
    )
    return response.choices[0].message.content

def extract_context(messages: list) -> dict:
    """Parse robot context from conversation. Stub for now."""
    return {"robot_type": "wheeled", "motors": 4, "power_source": "lipo_3s"}

def build_component_prompt(context: dict) -> str:
    return f"""
You are an expert robotics electrical engineer.
Given this robot specification, output a structured component list and netlist.

Robot specification:
{context}

Output JSON with:
- components: list of parts with name, role, count, reason
- nets: list of power/signal nets
- notes: design notes
""".strip()
