import httpx
from typing import Union, List, Dict, Any


async def simplified_chat(base_url: str, prompt: Union[str, List[Dict[str, Any]]], model: str, api_key: str, system_prompt: str = "") -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})

    if isinstance(prompt, str):
        full_messages.append({"role": "user", "content": prompt})
    elif isinstance(prompt, list):
        full_messages.extend(prompt)
    else:
        full_messages.append({"role": "user", "content": str(prompt)})

    data = {
        "model": model,
        "messages": full_messages
    }

    async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
        resp = await client.post(f"{base_url.rstrip('/')}/chat/completions", json=data)
        resp.raise_for_status()
        content = resp.json()
        return content["choices"][0]["message"]["content"]
