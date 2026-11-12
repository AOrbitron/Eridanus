from run.ai_generated_art.service.audit_policy import requires_nsfw_audit
from developTools.event.events import GroupMessageEvent
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager        
import asyncio
import random
import base64
import os
from developTools.message.message_components import File, Image, Video, Node, Text
from framework_common.utils.utils import delay_recall # 撤回提示防刷屏
from run.ai_generated_art.service.setu_moderate import pic_audit_standalone # 审核

from .comfy_api.client import ComfyUIClient
from .comfy_api.workflow import ComfyWorkflow

"""
最简单的文生图演示
"""

# Part 1: 服务器配置 + 全局轮询指针（替换原Queue方案）
COMFYUI_URLS = ["http://127.0.0.1:8188"]
# 全局索引变量：记录当前使用的服务器下标
current_server_index = 0

# Part 2: 核心工作流函数
async def run_workflow(prompt, config, output_dir: str = "data/pictures/cache"):
    """
    执行工作流并获取所有预定义的输出
    """
    # 声明使用全局索引变量
    global current_server_index
    # 获取当前服务器地址
    current_server_url = COMFYUI_URLS[current_server_index]
    print(f"\n本次执行使用服务器: {current_server_url}")
    
    # 更新全局指针：轮询切换下一个服务器（循环复用）
    current_server_index = (current_server_index + 1) % len(COMFYUI_URLS)

    # 导出的api工作流JSON文件的路径
    WORKFLOW_JSON_PATH = "run/comfyui_api/example_src/simple_t2i.json"

    if not os.path.exists(WORKFLOW_JSON_PATH):
        print(f"错误: 找不到工作流文件: {WORKFLOW_JSON_PATH}"); return
    
    async with ComfyUIClient(current_server_url, proxy=config.common_config.basic_config["proxy"]["http_proxy"] if config.common_config.basic_config["proxy"].get("http_proxy") else None) as client:
        
        workflow = ComfyWorkflow(WORKFLOW_JSON_PATH)

        # 种子一定要和上一次执行不同，否则不会返回内容
        if prompt != "default":
            workflow.add_replacement("6", "text", prompt)
        workflow.add_replacement("3", "seed", random.randint(0, 999999999999))

        # 4. 从节点(SaveImage) 触发默认下载，最终的输出将会是DEFAULT_DOWNLOAD键内
        workflow.add_output_node("9")

        # 一次性执行并获取所有结果
        print("\n开始执行工作流，完成后将一次性返回所有结果...")
        all_results = await client.execute_workflow(workflow, output_dir)

        print("\n工作流全部输出结果")
        # 使用json.dumps美化输出，方便查看
        #print(json.dumps(all_results, indent=2, ensure_ascii=False))
        #print("输出完毕")
        return all_results

async def call_simple_draw(bot, event, config, prompt): # 主调用逻辑和@bot.on分开，方便函数调用
    msg = await bot.send(event, "已发送cui绘图请求...")
    await delay_recall(bot, msg, 10)
    results = await run_workflow(prompt=prompt, config=config)
    path = results.get("9", {}).get("DEFAULT_DOWNLOAD", "")
    with open(path, "rb") as image_file:
        image_data = image_file.read()
    if requires_nsfw_audit(config.ai_generated_art.config['ai绘画'], event.group_id): # 审核逻辑开始
        try:
            check = await pic_audit_standalone(
                base64.b64encode(image_data).decode('utf-8'),
                return_none=True,
                url=config.ai_generated_art.config['ai绘画']['sd审核和反推api']
            )
        except:
            msg = await bot.send(event, "未配置审核api或api故障，为保证安全已禁止发送", True)
            await delay_recall(bot, msg, 10)
            return
        if check:
            msg = await bot.send(event, "杂鱼，色图不给你！", True)
            await delay_recall(bot, msg, 10)
            return # 审核逻辑结束，如果不想要审核可以把开始到结束的一段都删了
    await bot.send(event, [Text("cui结果:"), Image(file=path)], True)
    
def main(bot: ExtendBot,config: YAMLManager):
    @bot.on(GroupMessageEvent)
    async def handle_group_message(event: GroupMessageEvent):
        if event.pure_text.startswith("#cui "): # 触发指令前缀
            prompt = event.pure_text.replace("#cui ","")
            await call_simple_draw(bot, event, config, prompt)