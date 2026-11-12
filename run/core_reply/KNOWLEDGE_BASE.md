# 多知识库

复用现有 RAG 的 SQLite 数据库与 Embedding，不新增依赖、数据库服务或独立配置文件。
在 rag.yaml 开启 RAG 总开关及 knowledge_base.enable，注册知识库后重启 Bot：

    knowledge_base:
      enable: true
      libraries:
        - name: manual
          path: data/knowledge/manual
          enable: true

把 UTF-8 .txt 或 .md 文档放入该目录，启动及默认每 300 秒后台增量同步。
删除文档会删除对应索引；单文档读取、编码或向量化失败保留上次索引，目录扫描失败
不清空已有数据。目录必须在项目内 data/knowledge 的子目录，拒绝符号链接、重名库
及重叠目录。data/knowledge 已被 Git 忽略，不应提交用户文档。

知识库在现有 RAG 允许的私聊及白名单群聊间共享，不是每用户隔离存储。不要放入
只允许某个用户或群查看的资料。参考资料带库名、文件名和章节，独立于长期记忆注入，
不写入对话记忆。关闭知识库不影响原有记忆模式，检索失败或超时回退到普通回复。

只有确有需要时才调整以下调优字段。配置保留完整键以兼容项目的更新合并器，
不需要新增独立配置文件；使用默认值即可运行：
- root_dir: data/knowledge；自定义项目内路径需自行加入 Git 忽略。
- sync.on_startup: true、sync.interval_seconds: 300（设为 0 关闭周期扫描）。
- chunk.max_chars: 1000、chunk.overlap_chars: 120（不超过块长一半）。
- retrieval.min_similarity: 0.35、candidate_k: 20、top_k: 4、
  max_prompt_chars: 1600、timeout_seconds: 10。最后两项分别是注入字符预算和整次查询预算。

可选重排使用通用 /rerank HTTP 接口，默认关闭。按服务商填写
reranker.enable、base_url、api_key、model；默认模型为
BAAI/bge-reranker-v2-m3，默认地址为 https://api.siliconflow.cn/v1。
也可设置 endpoint（默认 rerank）和 timeout_seconds（默认 10）。
服务不可用、返回索引/分数非法时保留余弦相似度排序，不阻断回复。

维护入口：service/rag_knowledge.py 负责扫描、切块、同步和检索；
RAGMemory 管理生命周期，ReplyEngine 并行召回并在取消时回收子任务，
PromptBuilder 只负责带来源的参考资料注入。数据库、磁盘与向量排序在线程执行。
