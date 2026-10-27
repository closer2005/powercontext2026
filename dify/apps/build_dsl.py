#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离谱法庭 · The Absurd Court
生成 Dify 1.18.0（DSL 0.7.0）可导入的 Chatflow DSL：apps/absurd-court.chatflow.yml

用法：
    python apps/build_dsl.py                          # 使用默认占位 dataset_id（空）
    python apps/build_dsl.py --dataset-id <uuid>      # 绑定真实知识库后生成
    python apps/build_dsl.py --clerk-base http://host.docker.internal:8899
    python apps/build_dsl.py --out apps/absurd-court.chatflow.yml

字段依据（Dify 1.18.0 实际源码）：
  - graphon 0.8.0（api/pyproject.toml 固定 revision 4fa2214）
    节点实体：graphon/nodes/{llm,http_request,if_else,code,answer,variable_assigner,template_transform}/entities.py
  - api/core/workflow/nodes/knowledge_retrieval/entities.py（knowledge-retrieval 节点）
  - web/app/components/workflow/nodes/*/default.ts、types.ts（Web 端导出结构）
  - api/tests/fixtures/workflow/*.yml（导入格式夹具）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    raise

APP_NAME = "离谱法庭 · The Absurd Court"
APP_DESC = (
    "在线起诉任何东西：通敌的充电线、恶意循环的周一、非法占床的猫。"
    "AI 法官包青天 2.0 开庭、被告物件成精狡辩、你补充证据自由辩论，"
    "最后法官检索《荒诞法典》并参考你的旧案底，当庭宣读一份离谱判决书——案卷永久归档在 seekdb。"
)
ICON = "⚖️"
ICON_BG = "#FFEAD5"
DSL_VERSION = "0.7.0"

# Dify 中的 OpenAI 兼容 provider（env-engineer 配置 llama.cpp 的 OpenAI 兼容服务）
DEFAULT_PROVIDER = "langgenius/openai_api_compatible/openai_api_compatible"
DEFAULT_MODEL = "qwen2.5-3b-instruct"
DEFAULT_CLERK_BASE = "http://host.docker.internal:8899"

# 温度：解析 0.2 / 开庭·辩论 0.9 / 判决 0.8（DESIGN §4）
T_PARSE = 0.2
T_OPENING = 0.85
T_TALK = 0.9
T_VERDICT = 0.8

# 会话变量（DESIGN §4）
CONV_VARS = [
    ("stage", "idle", "阶段：idle=未开庭 / debate=辩论中"),
    ("case_no", "", "当前案号，如 #0042"),
    ("defendant", "", "当前被告"),
    ("charge", "", "当前罪名"),
    ("claim", "", "原告诉求"),
    ("precedent", "", "上一场检索到的先例文本"),
]

# 宣判关键词（stage=debate 时命中即宣判；顺序即优先级）
VERDICT_KEYWORDS = ["宣判", "判决", "结案", "判吧", "判了"]


def uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

JUDGE_PERSONA = """你是《离谱法庭》的主审法官「包青天 2.0」：一个自称日断阳、夜断阴，实际只会用网络梗和市井口吻判案的 AI 法官。
【人设】口头禅是"本官""升堂""大胆""带被告上来"；威严但不吓人，爱用"离谱""离大谱""本官给整不会了""退堂鼓不是这么打的"这类现代口语；偶尔假装拍惊堂木。
【风格】像说书人一样短、狠、好笑，但始终是"法庭"的口吻，不是脱口秀。"""

HARD_RULES = """【硬性约束（必须遵守）】
1. 全部使用简体中文（可少量 emoji），不要出现其他语言。
2. 只调侃物品、动植物、抽象概念与生活现象（充电线、周一、猫、体重秤……），严禁针对任何真实个人、职业、性别、地域、民族、宗教、身体特征等进行攻击、歧视或嘲讽。
3. 不输出暴力、血腥、违法、色情、恐怖、自伤等任何有害内容；罚则必须荒诞且无害（唱摇篮曲、写检讨、赔偿一块饼干、当庭道歉等）。
4. 不编造真实法律条文，不提供任何现实法律建议。
5. 严格按要求的字数和格式输出，不要输出 Markdown 标题、不要输出"以上""希望有帮助"等客套话。"""

PARSE_SYSTEM = """你是《离谱法庭》的书记员，负责把原告的一句话诉讼整理成"立案要素"。
【输出格式】只输出一个 JSON 对象，不要输出解释，不要使用 Markdown 代码块：
{"defendant":"被告名称","charge":"罪名","claim":"原告诉求","evidence":"证据摘要"}
【字段要求】
- defendant：一个具体的物件、动植物、抽象概念或生活现象，如"充电线""周一""我家的猫""体重秤""深夜外卖的香味"。
- charge：6 个字以内的罪名，如"通敌""非法占床""恶意循环""超时沉默"。
- claim：一句话诉求，不超过 30 字；原告没写就用"要求被告当庭道歉"。
- evidence：不超过 40 字的证据摘要；原告没提供就写"暂无书面证据，仅凭原告口述"。
【容错】即使原告输入毫无意义（比如 asdf、123、一堆乱码），你也要编出合理的被告、罪名、诉求，保证能够立案；绝不能拒绝立案，绝不能输出 JSON 以外的任何内容。"""

PARSE_USER = """原告的诉讼请求如下，请立案并输出 JSON：

{{#sys.query#}}"""

OPENING_SYSTEM = """{persona}

【角色】你（法官）与"原告"都是人类；"被告"是被告物件本人。本场你只负责**法官的开庭词**，不要替被告说话。

【任务】输出法官开庭词，1~2 句，必须完整包含本案案号（照抄提示中的案号，如"离谱刑初字第0042号"）。可以威严、可以嫌弃、可以用网络梗。

{rules}

【长度】40~100 字。只输出法官台词本身，不要写"法官："前缀、不要编号、不要替被告说话、不要提任何旧案/判例（旧案由系统另行播报）。""".format(persona=JUDGE_PERSONA, rules=HARD_RULES)

OPENING_USER = """案号：{{#conversation.case_no#}}
被告：{{#conversation.defendant#}}
罪名：{{#conversation.charge#}}
诉求：{{#conversation.claim#}}

请只输出法官的开庭词（必须含本案案号；不要写被告的台词，不要提旧案）。"""

DEFENDANT_SYSTEM = """你是《离谱法庭》里被起诉的"被告"——一件成精的物品、动物、抽象概念或生活现象，现在要当庭狡辩。
【任务】用第一人称说 1~2 句狡辩、耍赖或反诉，必须体现被告自身的物件特点（充电线聊电流/接口，猫聊睡觉，周一聊日历，体重秤聊数字）。
【格式】只输出台词本身（30~80 字），不要写"被告：""被告「…」："之类的前缀（前缀由系统统一加上），不要写法官的话，不要解释。
【示例】"本官冤枉！我只是传输电能，是插座先勾引我的！"
{rules}""".format(rules=HARD_RULES)

DEFENDANT_USER = """本案信息：
案号：{{#conversation.case_no#}}
被告：{{#conversation.defendant#}}
罪名：{{#conversation.charge#}}
诉求：{{#conversation.claim#}}
原告的指控：{{#sys.query#}}

请以被告的身份当庭狡辩（只输出台词本身）。"""

PRECEDENT_CODE = r'''
import re


def main(precedent_text: str) -> dict:
    text = precedent_text or ""
    m = re.search(r"#(\d{4})", text)
    if not m:
        return {"note": ""}
    no = m.group(1)
    return {"note": "📜 本官翻了案底：此被告有旧案 #%s，本次参照旧案 #%s 从重审理。" % (no, no)}
'''.strip()

DEBATE_SYSTEM = """{persona}

【角色】"原告"是起诉的人类；"被告"是被起诉的物件本人。两者不能混淆，绝对不要写"原告「<物件名>」"。

【任务】现在是自由辩论阶段，原告刚刚补充了证据或说法。请输出**恰好两行**：
第一行：法官：<一句点评，20~50 字，可以质疑也可以警告被告>
第二行：被告「<被告名称>」："<一句反驳，20~50 字>"

【格式要求】必须严格两行；第一行以"法官："开头，第二行以"被告「<被告名称>」："开头；合计不超过 160 字。示例：
法官：这点证据有点意思，被告你怎么解释？
被告「充电线」："我只是发热，又不是发疯，本官明察！"

{rules}""".format(persona=JUDGE_PERSONA, rules=HARD_RULES)

DEBATE_USER = """当前案号：{{#conversation.case_no#}}
被告：{{#conversation.defendant#}}｜罪名：{{#conversation.charge#}}｜诉求：{{#conversation.claim#}}
原告刚刚说：{{#sys.query#}}

请继续开庭辩论。"""

VERDICT_SYSTEM = """{persona}

【任务】现在必须当庭宣判。请综合案号、被告、罪名、诉求、原告旧案先例（可能为空）、《荒诞法典》法条原文，写一份离谱但痛快的判决书。
【输出格式】只输出一个 JSON 对象，不要输出解释，不要使用 Markdown 代码块：
{{"verdict":"罪名成立" 或 "罪名不成立","penalty":"荒诞罚则（≤40字）","judgment":"判决书正文（80~200字）"}}
【判决书正文要求】
- 必须以"本院认为"开头；
- 必须引用检索到的法典条文，写成"根据《荒诞法典》第N条"（N 取法条原文中真实存在的编号）；
- 如果给了旧案先例（文本里出现形如 #0001 的案号），必须写一句"参照第0001号判例，本院决定从重判处/从轻判处"（用先例里真实出现的数字，不许写"第X号"占位符）；没有先例就不要编造；
- 结尾写"退庭。"。

{rules}

【罚则示例】罚它为原告连唱三夜摇篮曲；责令其手写八百字检讨；赔偿原告一块饼干和一次满电出门的机会。""".format(persona=JUDGE_PERSONA, rules=HARD_RULES)

VERDICT_USER = """当前案号：{{#conversation.case_no#}}
被告：{{#conversation.defendant#}}
罪名：{{#conversation.charge#}}
诉求：{{#conversation.claim#}}

【旧案/先例（系统已校验；若为"无"则本场是首例，禁止提及任何判例或旧案号）】
{{#verdict_precedent.text#}}

与本案相关的《荒诞法典》法条原文：
{{#join_codex.codex#}}

原告最后的发言：{{#sys.query#}}

请宣判，只输出 JSON。"""

VERDICT_PRECEDENT_CODE = r'''
import re


def main(precedent_text: str) -> dict:
    text = (precedent_text or "").strip()
    if re.search(r"#\d{4}", text):
        return {"text": text[:500]}
    return {"text": "无（本场为首次出现的被告类型）"}
'''.strip()

HELP_ANSWER = """⚖️ 欢迎来到离谱法庭 · The Absurd Court

【四步玩法】
1️⃣ 立案：直接说你要起诉什么，例如「我要起诉我家的充电线，罪名是通敌，要求它当庭道歉」。
2️⃣ 开庭：本官当庭宣读案号并检索你的旧案底，被告（物件成精）会当场狡辩或反诉。
3️⃣ 辩论：继续补充证据、威胁、求情、胡搅蛮缠，法官和被告都会接话。
4️⃣ 宣判：输入「宣判」，本官检索《荒诞法典》并参考先例，当庭宣读离谱判决书，案卷归档进 seekdb。

📜 输入「查阅我的案底」可查看立案数、胜败战绩与你的法庭称号。
🧾 示例：「我要起诉周一，罪名是恶意循环，要求它赔偿一个周末」

（想结案请输入「宣判」；想换一场官司请先宣判，或随时输入「怎么玩」回来看说明。）"""

VERDICT_SUFFIX = """
——————
（输入「查阅我的案底」看统计，或直接发起下一场诉讼。）"""

OPENING_SUFFIX = """
（补充证据继续辩论，或输入「宣判」结案）"""

DEBATE_SUFFIX = """
（补充证据继续辩论，或输入「宣判」结案）"""


# ---------------------------------------------------------------------------
# 节点 / 连线构造函数
# ---------------------------------------------------------------------------


def _judge_memory():
    return {
        "role_prefix": {"user": "", "assistant": ""},
        "window": {"enabled": True, "size": 10},
        "query_prompt_template": "{{#sys.query#}}",
    }


def llm_node(node_id, title, system_prompt, user_prompt, temperature, max_tokens=None):
    completion_params = {"temperature": temperature}
    if max_tokens:
        completion_params["max_tokens"] = max_tokens
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": 0, "y": 0},
        "positionAbsolute": {"x": 0, "y": 0},
        "width": 244,
        "height": 98,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "llm",
            "title": title,
            "desc": "",
            "selected": False,
            "model": {
                "provider": DEFAULT_PROVIDER,
                "name": DEFAULT_MODEL,
                "mode": "chat",
                "completion_params": completion_params,
            },
            "prompt_template": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_prompt},
            ],
            "prompt_config": {"jinja2_variables": []},
            "memory": _judge_memory(),
            "context": {"enabled": False, "variable_selector": []},
            "vision": {"enabled": False},
            "variables": [],
            "selected": False,
        },
    }


def code_node(node_id, title, code, variables, outputs):
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": 0, "y": 0},
        "positionAbsolute": {"x": 0, "y": 0},
        "width": 244,
        "height": 98,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "code",
            "title": title,
            "desc": "",
            "selected": False,
            "code_language": "python3",
            "code": code,
            "variables": [{"variable": name, "value_selector": sel} for name, sel in variables],
            "outputs": {name: {"type": typ, "children": None} for name, typ in outputs},
        },
    }


def http_node(node_id, title, url, body_template, method="post"):
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": 0, "y": 0},
        "positionAbsolute": {"x": 0, "y": 0},
        "width": 244,
        "height": 98,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "http-request",
            "title": title,
            "desc": "",
            "selected": False,
            "method": method,
            "url": url,
            "authorization": {"type": "no-auth", "config": None},
            "headers": "",
            "params": "",
            "body": {
                "type": "json",
                "data": [{"key": "", "type": "text", "value": body_template}],
            },
            "timeout": {"connect": 10, "read": 60, "write": 30},
            "retry_config": {"retry_enabled": False, "max_retries": 1, "retry_interval": 1000},
            "ssl_verify": False,
            "variables": [],
        },
    }


def answer_node(node_id, title, answer):
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": 0, "y": 0},
        "positionAbsolute": {"x": 0, "y": 0},
        "width": 244,
        "height": 98,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "answer",
            "title": title,
            "desc": "",
            "selected": False,
            "answer": answer,
            "variables": [],
        },
    }


def assigner_node(node_id, title, items):
    """items: [(conversation_var_name, input_type, value)]"""
    out_items = []
    for var_name, input_type, value in items:
        out_items.append(
            {
                "variable_selector": ["conversation", var_name],
                "input_type": input_type,
                "operation": "over-write",
                "value": value,
            }
        )
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": 0, "y": 0},
        "positionAbsolute": {"x": 0, "y": 0},
        "width": 244,
        "height": 110,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "assigner",
            "title": title,
            "desc": "",
            "selected": False,
            "version": "2",
            "items": out_items,
        },
    }


def _condition(var_selector, operator, value, var_type="string"):
    return {
        "id": uid(),
        "varType": var_type,
        "variable_selector": var_selector,
        "comparison_operator": operator,
        "value": value,
    }


def build_route_node():
    cases = []

    # case1 玩法说明：query contains 怎么玩 / 玩法 / 规则
    cases.append(
        {
            "case_id": "case_help",
            "logical_operator": "or",
            "conditions": [
                _condition(["sys", "query"], "contains", "怎么玩"),
                _condition(["sys", "query"], "contains", "玩法"),
                _condition(["sys", "query"], "contains", "规则"),
            ],
        }
    )
    # case2 查案底：query contains 案底 / 档案 / 战绩
    cases.append(
        {
            "case_id": "case_stats",
            "logical_operator": "or",
            "conditions": [
                _condition(["sys", "query"], "contains", "案底"),
                _condition(["sys", "query"], "contains", "档案"),
                _condition(["sys", "query"], "contains", "战绩"),
            ],
        }
    )
    # case3 宣判：stage == debate AND query contains 关键词（每个关键词一个 case，按顺序短路）
    for idx, kw in enumerate(VERDICT_KEYWORDS):
        cases.append(
            {
                "case_id": "case_verdict_%d" % idx,
                "logical_operator": "and",
                "conditions": [
                    _condition(["conversation", "stage"], "is", "debate"),
                    _condition(["sys", "query"], "contains", kw),
                ],
            }
        )
    # case4 普通辩论：stage == debate
    cases.append(
        {
            "case_id": "case_debate",
            "logical_operator": "and",
            "conditions": [
                _condition(["conversation", "stage"], "is", "debate"),
            ],
        }
    )
    branches = [{"id": c["case_id"], "name": ("CASE %d" % (i + 1))} for i, c in enumerate(cases)]
    branches.append({"id": "false", "name": "ELSE"})
    return {
        "id": "route",
        "type": "custom",
        "position": {"x": 380, "y": 300},
        "positionAbsolute": {"x": 380, "y": 300},
        "width": 244,
        "height": 180,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "if-else",
            "title": "意图路由",
            "desc": "玩法说明 / 查案底 / 宣判 / 辩论 / 新案件 五路分支，顺序即优先级",
            "selected": False,
            "cases": cases,
            "_targetBranches": branches,
            "isInIteration": False,
            "isInLoop": False,
        },
    }


def build_knowledge_retrieval_node(dataset_id):
    return {
        "id": "retrieve_codex",
        "type": "custom",
        "position": {"x": 1090, "y": 420},
        "positionAbsolute": {"x": 1090, "y": 420},
        "width": 244,
        "height": 98,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "knowledge-retrieval",
            "title": "检索《荒诞法典》",
            "desc": "从 Dify 知识库（seekdb 向量存储）召回相关法条，top_k=3 / score≥0.2",
            "selected": False,
            "query_variable_selector": ["codex_query", "output"],
            "dataset_ids": [dataset_id] if dataset_id else [],
            "retrieval_mode": "multiple",
            "multiple_retrieval_config": {
                "top_k": 3,
                "score_threshold": 0.2,
                "reranking_mode": "reranking_model",
                "reranking_enable": False,
                "reranking_model": None,
                "weights": None,
            },
            "metadata_filtering_mode": "disabled",
            "vision": {"enabled": False},
        },
    }


def build_template_node():
    return {
        "id": "codex_query",
        "type": "custom",
        "position": {"x": 780, "y": 420},
        "positionAbsolute": {"x": 780, "y": 420},
        "width": 244,
        "height": 98,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": {
            "type": "template-transform",
            "title": "拼装检索词",
            "desc": "被告 + 罪名 + 诉求，作为知识库检索 query",
            "selected": False,
            "template": "{{ defendant }} {{ charge }} {{ claim }}",
            "variables": [
                {"variable": "defendant", "value_selector": ["conversation", "defendant"]},
                {"variable": "charge", "value_selector": ["conversation", "charge"]},
                {"variable": "claim", "value_selector": ["conversation", "claim"]},
            ],
        },
    }


# ---------------------------------------------------------------------------
# 节点代码
# ---------------------------------------------------------------------------

PARSE_CODE = r'''
import json
import re


def main(llm_text: str) -> dict:
    text = (llm_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    obj = {}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
        except Exception:
            obj = {}
    if not isinstance(obj, dict):
        obj = {}

    defendant = str(obj.get("defendant") or "").strip() or "某个说不清的东西"
    charge = str(obj.get("charge") or "").strip() or "非法存在"
    claim = str(obj.get("claim") or "").strip() or "要求被告当庭道歉"
    evidence = str(obj.get("evidence") or "").strip() or "暂无书面证据，仅凭原告口述"
    return {
        "defendant": defendant[:60],
        "charge": charge[:30],
        "claim": claim[:80],
        "evidence": evidence[:120],
        "ok": "true",
    }
'''.strip()

JOIN_CODEX = r'''
def main(result: list) -> dict:
    parts = []
    for item in (result or []):
        if isinstance(item, dict):
            content = item.get("content") or ""
        else:
            content = str(item)
        content = str(content).strip()
        if content:
            parts.append(content)
    text = "\n\n".join(parts)
    if not text:
        text = "（本院暂时没有检索到匹配的法条，请依据法庭常识宣判）"
    return {"codex": text[:800]}
'''.strip()

VERDICT_CODE = r'''
import json
import re


def main(llm_text: str, precedent_text: str) -> dict:
    text = (llm_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    obj = {}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
        except Exception:
            obj = {}
    if not isinstance(obj, dict):
        obj = {}

    verdict = str(obj.get("verdict") or "").strip()
    if verdict not in ("罪名成立", "罪名不成立"):
        verdict = "罪名成立"
    penalty = str(obj.get("penalty") or "").strip() or "罚它为原告当庭道歉三次"
    judgment = str(obj.get("judgment") or "").strip()

    # 确定性校验：seekdb 案卷库里没有真实旧案号时，删掉模型脑补出来的"参照…判例"句子
    if not re.search(r"#\d{4}", precedent_text or ""):
        judgment = re.sub(r"[^。；\n]*参照[^。；\n]*判例[^。；\n]*[。；]?", "", judgment).strip()

    if not judgment:
        judgment = "本院认为，被告的行为确实离谱，但卷宗证据有限，本案责令被告当庭道歉、赔偿原告一块饼干，退庭。"
    return {
        "verdict": verdict,
        "penalty": penalty[:80],
        "judgment": judgment[:400],
        "ok": "true",
    }
'''.strip()


# ---------------------------------------------------------------------------
# 主构建
# ---------------------------------------------------------------------------


def build_graph(dataset_id: str, clerk_base: str):
    c = clerk_base.rstrip("/")
    nodes = []

    # --- 入口与路由 ---
    nodes.append(
        {
            "id": "start",
            "type": "custom",
            "position": {"x": 80, "y": 300},
            "positionAbsolute": {"x": 80, "y": 300},
            "width": 244,
            "height": 54,
            "selected": False,
            "sourcePosition": "right",
            "targetPosition": "left",
            "data": {"type": "start", "title": "开始", "desc": "", "variables": [], "selected": False},
        }
    )
    nodes.append(build_route_node())

    # --- 玩法说明 ---
    nodes.append(_place(answer_node("help_answer", "玩法说明", HELP_ANSWER), 900, 40))

    # --- 查案底 ---
    nodes.append(
        _place(
            http_node(
                "stats_http",
                "查案底",
                c + "/api/stats",
                json.dumps({"plaintiff": "{{#sys.user_id#}}"}, ensure_ascii=False),
            ),
            900,
            210,
        )
    )
    nodes.append(_place(answer_node("stats_answer", "案底回执", "{{#stats_http.body#}}"), 1210, 210))

    # --- 宣判分支 ---
    nodes.append(build_template_node())
    nodes.append(build_knowledge_retrieval_node(dataset_id))
    nodes.append(
        _place(
            code_node(
                "join_codex",
                "拼装法条原文",
                JOIN_CODEX,
                [("result", ["retrieve_codex", "result"])],
                [("codex", "string")],
            ),
            1400,
            420,
        )
    )
    nodes.append(_place(llm_node("verdict_llm", "判决书生成", VERDICT_SYSTEM, VERDICT_USER, T_VERDICT, max_tokens=600), 1710, 420))
    nodes.append(
        _place(
            code_node(
                "verdict_precedent",
                "先例校验",
                VERDICT_PRECEDENT_CODE,
                [("precedent_text", ["conversation", "precedent"])],
                [("text", "string")],
            ),
            1400,
            560,
        )
    )
    nodes.append(
        _place(
            code_node(
                "verdict_code",
                "解析判决 JSON",
                VERDICT_CODE,
                [("llm_text", ["verdict_llm", "text"]), ("precedent_text", ["conversation", "precedent"])],
                [("verdict", "string"), ("penalty", "string"), ("judgment", "string"), ("ok", "string")],
            ),
            2020,
            420,
        )
    )
    nodes.append(
        _place(
            http_node(
                "archive",
                "案卷归档",
                c + "/api/cases/verdict",
                json.dumps(
                    {
                        "case_no": "{{#conversation.case_no#}}",
                        "verdict": "{{#verdict_code.verdict#}}",
                        "penalty": "{{#verdict_code.penalty#}}",
                        "judgment": "{{#verdict_code.judgment#}}",
                    },
                    ensure_ascii=False,
                ),
            ),
            2330,
            420,
        )
    )
    nodes.append(
        _place(
            answer_node(
                "verdict_answer",
                "判决书",
                "⚖️ 本官宣判：{{#verdict_code.verdict#}}\n\n{{#verdict_code.judgment#}}\n\n"
                "🔨 罚则：{{#verdict_code.penalty#}}\n\n{{#archive.body#}}" + VERDICT_SUFFIX,
            ),
            2640,
            420,
        )
    )
    nodes.append(
        _place(
            assigner_node("reset_vars", "结案清场", [("stage", "constant", "idle")]),
            2950,
            420,
        )
    )

    # --- 辩论分支 ---
    nodes.append(_place(llm_node("debate_llm", "法官与被告回应", DEBATE_SYSTEM, DEBATE_USER, T_TALK, max_tokens=400), 900, 620))
    nodes.append(
        _place(answer_node("debate_answer", "辩论回应", "{{#debate_llm.text#}}" + DEBATE_SUFFIX), 1210, 620)
    )

    # --- 新案件分支 ---
    nodes.append(_place(llm_node("parse_llm", "立案解析", PARSE_SYSTEM, PARSE_USER, T_PARSE, max_tokens=300), 900, 810))
    nodes.append(
        _place(
            code_node(
                "parse_code",
                "解析立案 JSON",
                PARSE_CODE,
                [("llm_text", ["parse_llm", "text"])],
                [
                    ("defendant", "string"),
                    ("charge", "string"),
                    ("claim", "string"),
                    ("evidence", "string"),
                    ("ok", "string"),
                ],
            ),
            1210,
            810,
        )
    )
    nodes.append(
        _place(
            http_node(
                "create_case",
                "立案登记",
                c + "/api/cases",
                json.dumps(
                    {
                        "plaintiff": "{{#sys.user_id#}}",
                        "defendant": "{{#parse_code.defendant#}}",
                        "charge": "{{#parse_code.charge#}}",
                        "claim": "{{#parse_code.claim#}}",
                        "evidence": "{{#parse_code.evidence#}}",
                    },
                    ensure_ascii=False,
                ),
            ),
            1520,
            810,
        )
    )
    nodes.append(
        _place(
            http_node(
                "search_precedent",
                "检索先例",
                c + "/api/cases/search",
                json.dumps(
                    {
                        "plaintiff": "{{#sys.user_id#}}",
                        "q": "{{#parse_code.defendant#}} {{#parse_code.charge#}}",
                        "limit": 3,
                    },
                    ensure_ascii=False,
                ),
            ),
            1830,
            810,
        )
    )
    nodes.append(
        _place(
            assigner_node(
                "set_vars",
                "写入庭审状态",
                [
                    ("stage", "constant", "debate"),
                    ("case_no", "variable", ["create_case", "body"]),
                    ("defendant", "variable", ["parse_code", "defendant"]),
                    ("charge", "variable", ["parse_code", "charge"]),
                    ("claim", "variable", ["parse_code", "claim"]),
                    ("precedent", "variable", ["search_precedent", "body"]),
                ],
            ),
            2140,
            810,
        )
    )
    # 开庭拆成两个 LLM 节点：法官开庭词 + 被告狡辩（3B 模型对"两段式"指令不稳定，拆分后各自短输出更可靠）
    # precedent_note：先例提示由 Code 节点确定性生成（有旧案才播报），避免 3B 模型脑补先例
    nodes.append(
        _place(
            code_node(
                "precedent_note",
                "先例播报",
                PRECEDENT_CODE,
                [("precedent_text", ["search_precedent", "body"])],
                [("note", "string")],
            ),
            2350,
            810,
        )
    )
    nodes.append(
        _place(llm_node("opening_llm", "法官开庭词", OPENING_SYSTEM, OPENING_USER, T_OPENING, max_tokens=300), 2560, 810)
    )
    nodes.append(
        _place(
            llm_node("defendant_llm", "被告狡辩", DEFENDANT_SYSTEM, DEFENDANT_USER, T_TALK, max_tokens=300),
            2870,
            810,
        )
    )
    nodes.append(
        _place(
            answer_node(
                "opening_answer",
                "开庭回执",
                "📁 立案成功，案号：{{#conversation.case_no#}}\n\n{{#precedent_note.note#}}\n{{#opening_llm.text#}}\n"
                "被告「{{#conversation.defendant#}}」：{{#defendant_llm.text#}}" + OPENING_SUFFIX,
            ),
            3180,
            810,
        )
    )

    # --- 连线 ---
    edges = []

    def add_edge(src, handle, tgt, s_type, t_type):
        edges.append(
            {
                "id": "%s-%s-%s" % (src, handle, tgt),
                "source": src,
                "sourceHandle": handle,
                "target": tgt,
                "targetHandle": "target",
                "type": "custom",
                "data": {
                    "isInIteration": False,
                    "isInLoop": False,
                    "sourceType": s_type,
                    "targetType": t_type,
                },
                "zIndex": 0,
            }
        )

    add_edge("start", "source", "route", "start", "if-else")
    add_edge("route", "case_help", "help_answer", "if-else", "answer")
    add_edge("route", "case_stats", "stats_http", "if-else", "http-request")
    add_edge("stats_http", "source", "stats_answer", "http-request", "answer")
    for idx in range(len(VERDICT_KEYWORDS)):
        add_edge("route", "case_verdict_%d" % idx, "codex_query", "if-else", "template-transform")
    add_edge("codex_query", "source", "retrieve_codex", "template-transform", "knowledge-retrieval")
    add_edge("retrieve_codex", "source", "join_codex", "knowledge-retrieval", "code")
    add_edge("join_codex", "source", "verdict_precedent", "code", "code")
    add_edge("verdict_precedent", "source", "verdict_llm", "code", "llm")
    add_edge("verdict_llm", "source", "verdict_code", "llm", "code")
    add_edge("verdict_code", "source", "archive", "code", "http-request")
    # Dify Chatflow 中 Answer 是终端输出节点，其后不再接节点：
    # 结案清场（reset_vars）放在判决书答案节点之前，只改 stage，不影响 Answer 渲染内容
    add_edge("archive", "source", "reset_vars", "http-request", "assigner")
    add_edge("reset_vars", "source", "verdict_answer", "assigner", "answer")
    add_edge("route", "case_debate", "debate_llm", "if-else", "llm")
    add_edge("debate_llm", "source", "debate_answer", "llm", "answer")
    add_edge("route", "false", "parse_llm", "if-else", "llm")
    add_edge("parse_llm", "source", "parse_code", "llm", "code")
    add_edge("parse_code", "source", "create_case", "code", "http-request")
    add_edge("create_case", "source", "search_precedent", "http-request", "http-request")
    add_edge("search_precedent", "source", "set_vars", "http-request", "assigner")
    add_edge("set_vars", "source", "precedent_note", "assigner", "code")
    add_edge("precedent_note", "source", "opening_llm", "code", "llm")
    add_edge("opening_llm", "source", "defendant_llm", "llm", "llm")
    add_edge("defendant_llm", "source", "opening_answer", "llm", "answer")

    return {"edges": edges, "nodes": nodes, "viewport": {"x": 0, "y": 0, "zoom": 0.7}}


def _place(node, x, y):
    node["position"] = {"x": x, "y": y}
    node["positionAbsolute"] = {"x": x, "y": y}
    return node


def build_dsl(dataset_id: str, clerk_base: str):
    conversation_variables = []
    for name, default, desc in CONV_VARS:
        conversation_variables.append(
            {
                "id": uid(),
                "name": name,
                "description": desc,
                "selector": ["conversation", name],
                "value": default,
                "value_type": "string",
            }
        )

    return {
        "app": {
            "name": APP_NAME,
            "description": APP_DESC,
            "icon": ICON,
            "icon_background": ICON_BG,
            "mode": "advanced-chat",
            "use_icon_as_answer_icon": False,
        },
        "dependencies": [],
        "kind": "app",
        "version": DSL_VERSION,
        "workflow": {
            "conversation_variables": conversation_variables,
            "environment_variables": [],
            "features": {
                "file_upload": {"enabled": False},
                "opening_statement": HELP_ANSWER,
                "retriever_resource": {"enabled": True},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False},
                "suggested_questions": [
                    "我要起诉我家的充电线，罪名是通敌，要求它当庭道歉",
                    "我要起诉周一，罪名是恶意循环，要求它赔偿我一个完整的周末",
                    "我要起诉我家的猫，罪名是非法占床",
                    "怎么玩？",
                ],
                "suggested_questions_after_answer": {"enabled": False},
                "text_to_speech": {"enabled": False, "language": "", "voice": ""},
            },
            "graph": build_graph(dataset_id, clerk_base),
        },
    }


class _Dumper(yaml.SafeDumper):
    pass


def _str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_representer)


def dump_yaml(data: dict) -> str:
    text = yaml.dump(
        data,
        Dumper=_Dumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=4096,
    )
    # 自检：必须能原样 round-trip，否则退回最保守的默认 dumper
    try:
        if yaml.safe_load(text) != data:
            raise ValueError("round-trip mismatch")
    except Exception:
        text = yaml.dump(
            data,
            Dumper=yaml.SafeDumper,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=4096,
        )
        assert yaml.safe_load(text) == data, "DSL YAML round-trip failed"
    return text


HEADER = """# ============================================================================
# 离谱法庭 · The Absurd Court — Dify 1.18.0 Chatflow DSL
# 本文件由 apps/build_dsl.py 生成，请勿手工编辑；重新生成：
#     python apps/build_dsl.py --dataset-id <知识库《荒诞法典》的 dataset UUID>
# 导入方式：Dify 控制台 → 创建应用 → 导入 DSL（或 POST /console/api/apps/imports）
# 模型：{provider} / {model}（可在画布中重新绑定任意 OpenAI 兼容模型）
# 书记员服务：{clerk}（记忆/案卷，Docker 内访问宿主机）
# 知识库：{dataset}
# ============================================================================

"""


def main(argv=None):
    global DEFAULT_PROVIDER, DEFAULT_MODEL
    parser = argparse.ArgumentParser(description="生成《离谱法庭》Dify Chatflow DSL")
    parser.add_argument("--dataset-id", default="", help="知识库《荒诞法典》的 dataset UUID（可留空，导入后重新绑定）")
    parser.add_argument("--clerk-base", default=DEFAULT_CLERK_BASE, help="书记员服务地址（默认 http://host.docker.internal:8899）")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="LLM provider id")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM 模型名")
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "absurd-court.chatflow.yml"),
        help="输出文件路径",
    )
    args = parser.parse_args(argv)

    DEFAULT_PROVIDER = args.provider
    DEFAULT_MODEL = args.model

    dsl = build_dsl(args.dataset_id.strip(), args.clerk_base.strip())
    text = HEADER.format(
        provider=DEFAULT_PROVIDER,
        model=DEFAULT_MODEL,
        clerk=args.clerk_base.strip(),
        dataset=args.dataset_id.strip() or "（未绑定，导入后需在 retrieve_codex 节点重新选择）",
    ) + dump_yaml(dsl)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

    graph = dsl["workflow"]["graph"]
    print("已生成：%s" % args.out)
    print("  节点 %d 个，连线 %d 条，会话变量 %d 个"
          % (len(graph["nodes"]), len(graph["edges"]), len(dsl["workflow"]["conversation_variables"])))
    print("  dataset_id：%s" % (args.dataset_id.strip() or "（空，导入后重新绑定）"))
    print("  clerk：%s" % args.clerk_base.strip())
    print("  model：%s / %s" % (DEFAULT_PROVIDER, DEFAULT_MODEL))
    return 0


if __name__ == "__main__":
    sys.exit(main())