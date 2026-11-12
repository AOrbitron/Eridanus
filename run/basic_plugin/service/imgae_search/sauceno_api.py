import asyncio
from httpx import AsyncClient
import os

async def saucenao(image_source, apiKey, proxies=None) -> list[list[str, str]]:
    """
    saucenao 以图搜图接口，支持网络 URL 以及本地文件路径（文件上传）。
    """
    url = "https://saucenao.com/search.php"

    def extract_results(data):
        results = data.get('results', [])[:2]
        results_data = []

        for result in results:
            header = result.get('header', {})
            data_info = result.get('data', {})

            result_str = f"saucenao搜图结果：\n相似度: {header.get('similarity', '')}\n"
            for key, value in data_info.items():
                result_str += f"{key}: {value}\n "

            result_str = result_str.rstrip(", ")
            results_data.append([header.get('thumbnail'), result_str])

        return results_data

    async with AsyncClient(proxies=proxies, timeout=30.0) as client:
        # 如果是本地文件且存在，走文件上传路径
        if isinstance(image_source, str) and os.path.exists(image_source):
            with open(image_source, "rb") as f:
                file_bytes = f.read()
            files = {"file": (os.path.basename(image_source), file_bytes, "image/jpeg")}
            data = {
                'output_type': '2',
                'api_key': apiKey,
            }
            response = await client.post(url, data=data, files=files)
        else:
            data = {
                'url': image_source,
                'output_type': '2',
                'api_key': apiKey,
            }
            response = await client.post(url, data=data)

        return extract_results(response.json())
