import httpx
import asyncio
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urljoin, quote, unquote
import gc

async def fetch_url(url, headers):
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=20.0)
        return response

def extract_div_contents(html_content):
    """从Baidu搜索结果HTML中提取标题、链接和内容。"""
    soup = BeautifulSoup(html_content, 'html.parser')
    result_op_divs = soup.find_all('div', class_='result-op c-container new-pmd')
    result_xpath_log_divs = soup.find_all('div', class_='result c-container xpath-log new-pmd')
    
    entries = []
    
    for div in result_op_divs + result_xpath_log_divs:
        title_tag = div.find('h3')
        title = title_tag.get_text(strip=True) if title_tag else "无标题"
        link_tag = div.find('a', href=True)
        link = link_tag['href'] if link_tag else "无链接"
        
        all_texts = [text for text in div.stripped_strings if text != title]
        content = ' '.join(all_texts)

        content = re.sub(r'UTC\+8(\d{5}:\d{2}:\d{2})', lambda x: 'UTC+8 ' + ':'.join([x.group(1)[i:i+2] for i in range(0, len(x.group(1)), 2)]).lstrip(':'), content)
        content = re.sub(r'(\d{2}:\d{2})(\d{4}-\d{2}-\d{2})', r'\1 \2', content)
        content = re.sub(r'(\d{2}) (\d{2}) : (\d{2}) (\d{2}) : (\d{2}) (\d{2})', r'\1:\3:\5', content)
        
        entries.append({
            'title': title,
            'link': link,
            'content': content
        })
        
    return entries

async def baidu_search(query):
    current_timestamp = int(time.time())
    url = f"https://www.baidu.com/s?wd={query}"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "identity",  # Request uncompressed content
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Connection": "keep-alive",
        "Cookie": "BAIDUID_BFESS=A66237379B97E6A261B58CF57A599B36:FG=1; BAIDU_WISE_UID=wapp_1735376969138_24; ZFY=SAnc8iRNM:ANXuj2oLMz5qIRu8biHnpXnJWjpW7TDpqQ:C; __bid_n=19411378e1092166a470ad; BDUSS=hrYmdrV3J6YURhcXNVdmhEdzl6R285cXlUOEUxTjljVThOZFlPdkt1ck1PTHhuSVFBQUFBJCQAAAAAAAAAAAEAAAC8k8VDx-W0v7XE0MfQxzIwMDkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMynlGfMp5RnWm; BDUSS_BFESS=hrYmdrV3J6YURhcXNVdmhEdzl6R285cXlUOEUxTjljVThOZFlPdkt1ck1PTHhuSVFBQUFBJCQAAAAAAAAAAAEAAAC8k8VDx-W0v7XE0MfQxzIwMDkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMynlGfMp5RnWm; RT=\"z=1&dm=baidu.com&si=67fe5ea0-9903-498c-8a2c-caac8abb3423&ss=m6rr8uo8&sl=2&tt=6lh&bcn=https%3A%2F%2Ffclog.baidu.com%2Flog%2Fweirwood%3Ftype%3Dperf&ld=6js&ul=82y&hd=838\"; BIDUPSID=A66237379B97E6A261B58CF57A599B36; PSTM=1738765634; BDRCVFR[BIVAaPonX6T]=-_EV5wtlMr0mh-8uz4WUvY; H_PS_PSSID=61027_61672_61987; BD_UPN=12314753; BA_HECTOR=ak0h04a58k80a0a1a42h00a08krj591jq6ta41v; delPer=0; BD_CK_SAM=1; PSINO=3; BDORZ=FFFB88E999055A3F8A630C64834BD6D0; channel=bing; baikeVisitId=ed9be3e1-1a99-40db-ba9e-5fb15086499e; sugstore=1; H_PS_645EC=b0c8DXwu1zardcmOPhN4OqPWlhNdg5njr4BBu4r%2FG3omWhcYKkp9EBJovo73j%2BCbdzDizw7sKluo",
        "DNT": "1",
        "Host": "www.baidu.com",
        "Referer": "https://www.baidu.com/s?wd=%E6%97%B6%E9%97%B4&base_query=%E6%97%B6%E9%97%B4&pn=0&oq=%E6%97%B6%E9%97%B4&tn=68018901_58_oem_dg&ie=utf-8&usm=4&rsv_idx=2&rsv_pq=db1e11ba0149dd28&rsv_t=051f4Gfs0d6O1kjBloAcKUq0VT1U06iWRPu%2FNeyVIvZiNPdxDgnaeJjnszjKZFtGWofQv4iUGorN",
        "Sec-Ch-Ua": "\"Not A(Brand\";v=\"8\", \"Chromium\";v=\"132\", \"Microsoft Edge\";v=\"132\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": "\"Windows\"",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "X-Custom-Time": str(current_timestamp),
    }
    
    response = await fetch_url(url, headers)
    html_content = response.text
    entries = extract_div_contents(html_content)

    del response
    del html_content

    result_parts = ["baidu搜索结果:"]
    for entry in entries:
        result_parts.append(f"标题: {entry['title']}\n链接: {entry['link']}\n内容: {entry['content']}\n" + "- " * 10)
        
    return "\n".join(result_parts)

async def searx_search(query):
    url = 'https://searx.bndkt.io/search'
    current_timestamp = int(time.time())
    params = {
        'q': query,
        'categories': 'general',
        'language': 'zh-CN',
        'time_range': '',
        'safesearch': '0',
        'theme': 'simple'
    }
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": "_pk_id.3.9c95=99d38b3e33bd1ecf.1738772334.; _pk_ses.3.9c95=1",
        "DNT": "1",
        "Host": "searx.bndkt.io",
        "Origin": "null",
        "Sec-Ch-Ua": "\"Not A(Brand\";v=\"8\", \"Chromium\";v=\"132\", \"Microsoft Edge\";v=\"132\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": "\"Windows\"",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "X-Custom-Time": str(current_timestamp),
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, headers=headers, timeout=20.0)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            del response
            
            articles = soup.find_all('article', class_='result result-default category-general')
            
            results = []
            for article in articles:
                title = article.find('h3').get_text(strip=True)
                link = article.find('a', class_='url_header')['href']
                content = article.find('p', class_='content').get_text(strip=True)
                results.append(f"标题: {title}\n链接: {link}\n内容: {content}\n{'- ' * 10}")
            del soup
            
            final_output = "searx搜索结果:\n" + "\n".join(results)
            return final_output
            
        except httpx.HTTPStatusError as exc:
            return f"HTTP错误: {exc}\n响应内容: {exc.response.text}"
        except httpx.RequestError as exc:
            return f"请求错误: {exc}"

async def html_read(url, config=None):
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Cache-Control": "max-age=0",
        "DNT": "1",
        "Priority": "u=0, i",
        "Referer": "https://github.com/",
        "Sec-Ch-Ua": "\"Not A(Brand\";v=\"8\", \"Chromium\";v=\"132\", \"Microsoft Edge\";v=\"132\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": "\"Windows\"",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0"
    }
    
    proxies = None
    if config and config.common_config.basic_config["proxy"]["http_proxy"]:
        proxies = {"http://": config.common_config.basic_config["proxy"]["http_proxy"], "https://": config.common_config.basic_config["proxy"]["http_proxy"]}

    decoded_url = unquote(url)
    parsed_url = httpx.URL(decoded_url)
    encoded_path = quote(parsed_url.path)
    encoded_url = str(parsed_url.copy_with(path=encoded_path))
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=None, proxies=proxies, headers=headers) as client:
            response = await client.get(encoded_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            base_url = str(response.url)
            del response

            if not soup.html:
                return "未找到<html>标签，请确认网页内容是否正确加载。"
            for script_or_style in soup(['script', 'style', 'meta', 'link']):
                script_or_style.decompose()
            def recurse(node, level=0, base_url_for_join=None):
                indent = '  ' * level
                result = []
                
                if hasattr(node, 'name') and node.name is not None:
                    tag_name = node.name.lower()

                    if tag_name in ['script', 'style']: return result
                    
                    if tag_name in ['pre', 'code']:
                        code_text = node.get_text()
                        lines = [line for line in code_text.split('\n') if line.strip()]
                        formatted_code = "\n".join([f"{indent}{line}" for line in lines])
                        if formatted_code:
                            result.append(f"{indent}```\n{formatted_code}\n{indent}```")
                        return result
                    
                    url_attributes = {'a': 'href', 'img': 'src', 'iframe': 'src'}
                    if tag_name in url_attributes:
                        attr = url_attributes[tag_name]
                        url_attr_value = node.get(attr, '')

                        if url_attr_value and not url_attr_value.lower().startswith('javascript:'):
                            full_url = urljoin(base_url_for_join, url_attr_value)
                            text_content = ' '.join(node.stripped_strings) or node.get('alt', 'link')
                            result.append(f"{indent}[{text_content}]({full_url})")
                        return result
                    for child in node.children:
                        result.extend(recurse(child, level + 1, base_url_for_join))
                        
                elif isinstance(node, str) and node.strip():
                    text = ' '.join(node.strip().split())
                    if text and not text.startswith("//<![CDATA[") and not text.endswith("//]]>"):
                        result.append(f"{indent}{text}")
                        
                return result
            target_node = soup.body if soup.body else soup
            extracted_info = recurse(target_node, base_url_for_join=base_url)

            del soup
            del target_node
            
            return "\n".join(extracted_info)
            
    except httpx.RequestError as e:
        return f"请求发生错误：{e}"
    except Exception as e:
        return f"处理时发生未知错误: {e}"

async def main():
    while True:
        url = input("请输入要测试的URL（或输入'exit'退出）：")
        if url.lower() == 'exit':
            break
        
        if url.startswith("baidu:"):
            query = url.split(":", 1)[1]
            result = await baidu_search(query)
        elif url.startswith("searx:"):
            query = url.split(":", 1)[1]
            result = await searx_search(query)
        else:
            result = await html_read(url)
            
        print(result)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已退出。")
