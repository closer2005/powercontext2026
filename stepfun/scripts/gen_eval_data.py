#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the deterministic Chinese corpus + evaluation query set used by the demo/benchmark.

Outputs (relative to stepfun/):
  data/corpus/docs.json      [{id,title,topic,text}]
  data/eval/queries.json     [{id,query,qrels:[doc_id...]}]

The corpus is a small hand-written Chinese knowledge base (64 short documents, 8 topics).
It is intentionally self-contained so that the quality benchmark (Recall@K / nDCG@K) is
reproducible without downloading a third-party dataset.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CORPUS = {
    "hangzhou": [
        ("西湖", "西湖景区环绕苏堤、白堤和杨公堤，适合环湖步行和骑行。春天看桃花，夏天赏荷花，晚上可以看音乐喷泉。"),
        ("灵隐寺", "灵隐寺位于飞来峰下，香火很旺，建议早上八点前到达避开人流。飞来峰石刻值得慢慢看，寺票和景区票需要分别购买。"),
        ("北高峰", "北高峰是杭州爬山的好去处，从灵隐寺旁边的步道上去大约四十分钟，山顶可以俯瞰西湖和城区，适合看日落。"),
        ("西溪湿地", "西溪湿地以水乡湿地景观著称，可以坐摇橹船穿行芦苇荡，秋天有柿子节。园区很大，建议预留半天时间。"),
        ("河坊街", "河坊街是老杭州的步行街，有很多小吃和手工艺品店，晚上人多热闹，附近还有南宋御街可以一起逛。"),
        ("宋城", "宋城以大型实景演出《宋城千古情》出名，园区内有很多仿古建筑和互动表演，适合带家人一起玩一整天。"),
        ("雷峰塔", "雷峰塔在西湖东南角，登塔可以看整个西湖全景，傍晚的夕照很漂亮。塔内有电梯，老人小孩也方便。"),
        ("龙井村", "龙井村在西湖西南的山里，春天可以看茶农采茶炒茶，找一家茶农家里喝新茶，顺便走一走九溪十八涧。"),
    ],
    "cafe": [
        ("湖滨路湖景咖啡馆", "湖滨路一带靠湖的咖啡馆，二楼靠窗位置正对西湖，适合下午晒太阳。咖啡价格偏贵，但环境很安静。"),
        ("写字楼连锁咖啡", "公司楼下的连锁咖啡店早上八点开门，拿铁和澳白都不错，工作日午休时间需要排队，出品速度快。"),
        ("书店二层咖啡区", "书店二层的咖啡区可以边看书边喝咖啡，座位不多但很安静，适合一个人待一下午，周末需要早点去占座。"),
        ("巷子里的自习咖啡馆", "开在巷子里的咖啡店，灯光柔和，背景音乐很轻，很多人带电脑办公。有插座和长桌，适合自习和写稿。"),
        ("宠物友好咖啡馆", "这家咖啡馆允许带狗进店，还会给狗狗准备水碗和零食。室外有围栏小院子，周末带宠物来玩的人很多。"),
        ("手冲精品咖啡", "老板做手冲很专业，豆单每周更换，会详细讲解风味。店里只有十几个座位，适合慢慢品尝。"),
        ("二十四小时咖啡店", "这家咖啡店二十四小时营业，深夜也能喝到热咖啡，附近加班的程序员常来。凌晨时段人少，适合赶项目。"),
        ("咖啡甜品店", "咖啡馆自家做巴斯克和提拉米苏，和深烘豆子搭配很好。下午茶套餐性价比高，建议两人分一份。"),
    ],
    "db": [
        ("seekdb 简介", "seekdb 是面向 AI 应用的数据库，支持向量检索和全文检索。通过 seekdb-js 可以在 Node 里创建集合、写入文档和向量。"),
        ("seekdb 全文索引", "seekdb 的全文索引支持 ik 中文分词，建集合时可以在 schema 里配置 FullTextIndexConfig。查询时用 whereDocument 的 contains 条件。"),
        ("seekdb HNSW 索引", "HNSW 是近似最近邻索引，seekdb 里可以配置 M、ef_construction 和 ef_search 参数，在召回率和延迟之间做权衡。"),
        ("seekdb 混合检索", "seekdb 的 hybridSearch 把向量检索和全文检索的结果用 RRF 融合，一次调用就能返回排序后的结果，不需要客户端自己拼合两路结果。"),
        ("OceanBase 分布式数据库", "OceanBase 是分布式关系数据库，支持多副本强一致和高压缩。seekdb 兼容 MySQL 协议，可以用 mysql 客户端连接。"),
        ("seekdb 索引刷新", "seekdb 的向量索引默认异步维护，写入后需要调用 refresh_index 或者 dbms_index_manager.refresh，新增文档才能被近似检索到。"),
        ("向量维度一致性", "创建集合时要指定向量维度，维度必须和 embedding 模型输出一致。bge-small-zh 输出 512 维，MiniLM 输出 384 维。"),
        ("SQL 查询优化", "写 SQL 时尽量利用索引列过滤，避免在 where 里对字段做函数运算。执行计划可以用 explain 查看。"),
    ],
    "ondevice": [
        ("Transformers.js 浏览器推理", "Transformers.js 可以在浏览器里运行 ONNX 模型，支持 feature-extraction 等任务，模型文件从 Hugging Face 下载后缓存在浏览器。"),
        ("WebGPU 加速", "WebGPU 能调用显卡做推理，速度通常比 WASM 快。用 Transformers.js 时把 device 设为 webgpu，并通过 requestAdapter 检查是否支持。"),
        ("WASM 自动降级", "当浏览器不支持 WebGPU 或者初始化失败时，可以自动降级到 WASM 后端，用 q8 量化模型保证兼容性，并在界面上提示当前后端。"),
        ("INT8 量化", "INT8 量化把模型权重从 32 位浮点压到 8 位整数，模型体积大约缩小到四分之一，推理速度也会提升，精度通常只有轻微下降。"),
        ("FP16 半精度", "FP16 用半精度浮点保存权重，模型体积约为 fp32 的一半。在支持 shader-f16 的 WebGPU 设备上可以用 fp16 加速推理。"),
        ("ONNX Runtime Web", "ONNX Runtime Web 提供 WASM 和 WebGPU 两种执行后端，模型加载时要指定执行提供器，推理时要把输入转成对应的张量。"),
        ("端侧推理性能", "端侧推理的瓶颈通常在模型加载和首次推理，预热之后单条文本的 embedding 延迟会明显下降，批处理能提高吞吐。"),
        ("模型缓存", "浏览器用 Cache Storage 缓存模型文件，第二次打开页面不需要重新下载。也可以用本地目录方式加载模型，避免依赖网络。"),
    ],
    "food": [
        ("杭帮菜", "杭帮菜口味清淡，东坡肉、龙井虾仁和西湖醋鱼是经典菜，游客多的店需要提前排队，本地人更常去社区小馆。"),
        ("川菜馆", "这家川菜馆的毛血旺和水煮鱼做得很地道，辣度可以调整，米饭免费续，晚上六点后需要等位。"),
        ("日料店", "日料店主打刺身和寿司，食材新鲜，午市定食比较划算。店面不大，建议提前订位。"),
        ("火锅店", "火锅店锅底选择多，毛肚和鸭肠是必点，营业到凌晨两点，适合朋友聚会，周末最好提前取号。"),
        ("老面馆", "老面馆的片儿川和拌川份量足，价格实惠，早上七点开门就有人排队，吃完可以去附近逛市场。"),
        ("素食餐厅", "素食餐厅环境清幽，菜品以豆制品和时蔬为主，摆盘精致，适合带长辈吃饭，人均稍高。"),
        ("夜宵摊", "夜宵摊的烤串和小龙虾很受欢迎，营业到凌晨，夏天人多，冬天有热汤和砂锅。"),
        ("甜品店", "甜品店的杨枝甘露和双皮奶评价很高，份量适中，下午茶时间人最多，可以外带。"),
    ],
    "sport": [
        ("西湖环湖跑步", "西湖环湖跑道一圈约十公里，早上人少空气好，晚上有灯光，沿途有补给点和公共厕所。"),
        ("钱塘江骑行", "之江路和钱塘江边适合骑行，路面平整车少，周末可以骑到钱江新城看江景，注意防晒。"),
        ("羽毛球馆", "羽毛球馆需要提前预约，工作日晚上和周末最紧张，场地按小时收费，可以租球拍。"),
        ("游泳馆", "游泳馆有标准泳道和儿童池，水温恒定，早场人少，需要带泳帽和健康证。"),
        ("健身房", "健身房二十四小时营业，器械比较新，私教课价格可以谈，晚上七点后比较拥挤。"),
        ("瑜伽馆", "瑜伽馆课程以流瑜伽和阴瑜伽为主，小班教学，老师会纠正体式，适合久坐的上班族。"),
        ("九溪爬山", "爬山可以从九溪上山，路线有台阶也有土路，来回大约三小时，记得带水和防蚊液。"),
        ("篮球场", "篮球场是塑胶地面，晚上有照明，周末经常有半场比赛，散场约球的人也不少。"),
    ],
    "code": [
        ("JavaScript 事件循环", "JavaScript 是单线程的，事件循环先执行同步代码，再处理微任务队列，最后处理宏任务，Promise 回调属于微任务。"),
        ("Node.js 服务端", "Node.js 基于 V8 和 libuv，适合做 IO 密集的服务。用 ES Module 时需要在 package.json 里设置 type 为 module。"),
        ("React 状态管理", "React 里小组件用 useState，跨组件共享状态可以用 Context 或者状态管理库，避免把状态放得太深。"),
        ("TypeScript 类型", "TypeScript 的泛型可以约束函数参数和返回值，联合类型配合类型收窄能减少运行时错误。"),
        ("Vite 构建工具", "Vite 开发时用原生 ES Module 按需编译，启动很快，生产构建用 Rollup 打包，配置简单。"),
        ("Git 分支管理", "Git 分支适合按功能开发，合并前先 rebase 保持历史整洁，提交信息要写清楚改了什么。"),
        ("单元测试", "单元测试用 Vitest 或 Jest，先测纯函数和边界情况，异步代码要注意 await 和超时。"),
        ("前端性能分析", "前端性能可以用 Chrome DevTools 的 Performance 面板分析，重点看长任务、重排重绘和网络请求瀑布。"),
    ],
    "study": [
        ("市图书馆自习区", "市图书馆自习区需要预约，早上九点开放，座位有插座和台灯，周一闭馆，考试季一座难求。"),
        ("付费自习室", "付费自习室按小时或包月收费，环境安静，有储物柜和茶水间，适合需要长时间专注的人。"),
        ("考研复习", "考研复习建议先过一遍基础再刷真题，专业课和数学要尽早开始，每周留时间复盘错题。"),
        ("英语听力练习", "练英语听力可以每天精听一段材料，先听大意再逐句听写，坚持一个月会有明显进步。"),
        ("读书笔记", "读书笔记不要只摘抄，写下自己的理解和疑问，定期回顾，把知识连成体系。"),
        ("时间管理", "时间管理可以用番茄工作法，二十五分钟专注加五分钟休息，晚上复盘当天完成的任务。"),
        ("在线课程", "在线课程要带着问题去学，边看边动手做练习，学完一章用自己的话总结一遍。"),
        ("论文阅读", "读论文先看摘要和结论，再读方法和实验部分，做好笔记记录关键数据和可复用的思路。"),
    ],
}


def main():
    docs = []
    topic_order = list(CORPUS)
    idx = 0
    for topic in topic_order:
        for title, text in CORPUS[topic]:
            idx += 1
            docs.append({
                "id": f"doc_{idx:03d}",
                "title": title,
                "topic": topic,
                "text": text,
            })

    # Map (topic, title) -> doc id to keep qrels readable below.
    by_title = {(d["topic"], d["title"]): d["id"] for d in docs}

    def ids(*pairs):
        return [by_title[p] for p in pairs]

    queries = [
        ("q01", "西湖附近安静适合看书的咖啡馆",
         ids(("cafe", "湖滨路湖景咖啡馆"), ("cafe", "书店二层咖啡区"), ("cafe", "巷子里的自习咖啡馆"))),
        ("q02", "杭州适合爬山看日落的地方",
         ids(("hangzhou", "北高峰"), ("sport", "九溪爬山"))),
        ("q03", "seekdb 怎么实现向量和全文混合检索",
         ids(("db", "seekdb 混合检索"), ("db", "seekdb 简介"))),
        ("q04", "浏览器里怎么用 WebGPU 跑 embedding 模型",
         ids(("ondevice", "WebGPU 加速"), ("ondevice", "Transformers.js 浏览器推理"))),
        ("q05", "INT8 量化后模型体积能压缩多少",
         ids(("ondevice", "INT8 量化"))),
        ("q06", "想找一家可以带狗去的咖啡店",
         ids(("cafe", "宠物友好咖啡馆"))),
        ("q07", "晚上加班想喝咖啡，哪里有二十四小时营业的店",
         ids(("cafe", "二十四小时咖啡店"))),
        ("q08", "灵隐寺附近有什么景点可以一起逛",
         ids(("hangzhou", "灵隐寺"), ("hangzhou", "北高峰"))),
        ("q09", "杭州周末骑行路线推荐",
         ids(("sport", "钱塘江骑行"))),
        ("q10", "React 里怎么管理全局状态",
         ids(("code", "React 状态管理"))),
        ("q11", "Node.js 里怎么跑单元测试",
         ids(("code", "单元测试"), ("code", "Node.js 服务端"))),
        ("q12", "seekdb 的 HNSW 索引参数怎么调",
         ids(("db", "seekdb HNSW 索引"))),
        ("q13", "推荐一家适合带长辈吃饭的素食餐厅",
         ids(("food", "素食餐厅"))),
        ("q14", "西湖玩一整天怎么安排",
         ids(("hangzhou", "西湖"), ("hangzhou", "河坊街"), ("hangzhou", "雷峰塔"))),
        ("q15", "想练英语听力，有什么练习方法",
         ids(("study", "英语听力练习"))),
        ("q16", "考研复习怎么安排时间和复盘",
         ids(("study", "考研复习"), ("study", "时间管理"))),
        ("q17", "seekdb 向量维度要和模型一致吗",
         ids(("db", "向量维度一致性"))),
        ("q18", "周末想打羽毛球，场地怎么预约",
         ids(("sport", "羽毛球馆"))),
        ("q19", "深夜里想吃小龙虾和烤串",
         ids(("food", "夜宵摊"))),
        ("q20", "模型第二次打开还要重新下载吗",
         ids(("ondevice", "模型缓存"))),
        ("q21", "WebGPU 不可用时怎么降级",
         ids(("ondevice", "WASM 自动降级"))),
        ("q22", "西溪湿地有什么好玩的",
         ids(("hangzhou", "西溪湿地"))),
        ("q23", "读论文有什么方法",
         ids(("study", "论文阅读"))),
        ("q24", "前端性能怎么用 DevTools 分析",
         ids(("code", "前端性能分析"))),
    ]

    qlist = [{"id": qid, "query": q, "qrels": rel} for qid, q, rel in queries]

    os.makedirs(os.path.join(ROOT, "data", "corpus"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "data", "eval"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "corpus", "docs.json"), "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=1)
    with open(os.path.join(ROOT, "data", "eval", "queries.json"), "w", encoding="utf-8") as f:
        json.dump(qlist, f, ensure_ascii=False, indent=1)
    with open(os.path.join(ROOT, "data", "eval", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"docs": len(docs), "queries": len(qlist), "topics": topic_order}, f, ensure_ascii=False, indent=1)
    print(f"wrote {len(docs)} docs, {len(qlist)} queries")


if __name__ == "__main__":
    main()