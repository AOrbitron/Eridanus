import traceback
import httpx

async def search_(img: str):
    """
    Eridanus项目提供的搜图服务端，需要额外部署。
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            with open(img, "rb") as f:
                files = {
                    "file": (img, f.read(), "image/jpeg")
                }
                headers = {
                    "accept": "application/json"
                }
                response = await client.post("http://127.0.0.1:5008/search", headers=headers, files=files)
                return response.json().get("results", [])
        except Exception as e:
            # 服务端未部署或连接失败时不阻塞
            return []
