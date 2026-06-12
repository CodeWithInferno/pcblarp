import os
from openai import OpenAI

# Nebius client for vision / 3D / heavy models.
# Same OpenAI-compatible API, just different model names.

def get_nebius_client():
    return OpenAI(
        api_key=os.getenv("NEBIUS_API_KEY"),
        base_url=os.getenv("NEBIUS_BASE_URL", "https://api.studio.nebius.ai/v1"),
    )

def nebius_vision_analysis(image_b64: str, prompt: str, model: str = "Qwen/Qwen2-VL-7B-Instruct") -> str:
    client = get_nebius_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }
        ],
        max_tokens=512,
    )
    return response.choices[0].message.content
