"""Read personal memory from the running engine, without legacy ai_llm data."""


async def query_user_profile(engine, group_id, user_id):
    context = engine.context
    sections = []
    for label, enabled, read in (
        ('Slots 记忆槽位', context.enable_memory_slots, lambda: context.get_user_memory(user_id)),
        ('Impression 用户印象', context.enable_impression, lambda: context.get_impression(user_id)),
    ):
        if not enabled:
            sections.append(f'{label}：未启用')
            continue
        try:
            sections.append(f'{label}：\n{read() or "暂无记录"}')
        except Exception:
            sections.append(f'{label}：查询失败，请稍后重试')
    try:
        rag = engine.rag_memory
        if not rag.allowed(group_id):
            sections.append('RAG 用户记忆：未启用（或当前会话不允许）')
        else:
            facts = await rag.query_user_facts(group_id, user_id)
            sections.append(f'RAG 用户记忆：\n{facts or "暂无记录"}')
    except Exception:
        sections.append('RAG 用户记忆：查询失败，请稍后重试')
    return sections
