import httpx


async def simplified_chat(base_url,prompt,model,api_key,system_prompt):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(prompt)
    data = {
        "model": model,
        "messages": prompt
    }

    async with httpx.AsyncClient(headers=headers,timeout=None) as client:
        content = await client.post(f"{base_url}/chat/completions",json=data)
        return content.json()["choices"][0]["message"]["content"]
