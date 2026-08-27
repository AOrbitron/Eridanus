import asyncio
from developTools.event.events import GroupMessageEvent
from developTools.message.message_components import Node, Text
from run.resource_collector.service.engine_search import baidu_search, searx_search, html_read

async def read_html(bot,event,config,url):
    bot.logger.info(f"正在阅读网页:{url}")
    if config.ai_llm.config["llm"]["联网搜索显示原始数据"]:
        await bot.send(event, f"正在阅读网页:{url}")
    html_content = await html_read(url, config)
    return  {"result": html_content}

async def search_net(bot,event,config,query):
    functions = [
        baidu_search(query),
        searx_search(query)
    ]
    
    tasks = [asyncio.create_task(func) for func in functions]
    final = ''
    sendMes = []
    for future in asyncio.as_completed(tasks):
        try:
            result = await future
            if result:
                sendMes.append(Node(content=[Text(result)]))
                final += result + '\n'
        except Exception as e:
            bot.logger.error(f"{e}")
    if config.ai_llm.config["llm"]["联网搜索显示原始数据"]:
        await bot.send(event, sendMes)
    return  {"result": final}

def main(bot,config):
    @bot.on(GroupMessageEvent)
    async def search111(event):
        return
        if str(event.pure_text).startswith("#搜索 "):
            query = str(event.pure_text).replace("#搜索 ", "")
            functions = [
                baidu_search(query),
                searx_search(query)
            ]
            
            tasks = [asyncio.create_task(func) for func in functions]
            sendMes = []
            for future in asyncio.as_completed(tasks):
                try:
                    result = await future
                    if result:
                        sendMes.append(Node(content=[Text(result)]))
                except Exception as e:
                    bot.logger.error(f"{e}")
            await bot.send(event, sendMes)
        else:
            pass
