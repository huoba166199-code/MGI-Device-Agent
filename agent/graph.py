import os
import re
import requests
import signal
from langgraph.graph import StateGraph, END
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import HumanMessage
from .state import AgentState
from .rag import search_manual
from dotenv import load_dotenv

load_dotenv()

llm = ChatDeepSeek(
    api_key=os.getenv("LLM_API_KEY"),
    api_base=os.getenv("LLM_API_BASE"),
    model=os.getenv("LLM_MODEL"),
    temperature=0.1
)


# ================= 定义独立节点 =================

def parse_input_node(state: AgentState):
    """节点 1：解析用户输入，提取特征"""
    print("📌 [节点1] 正在解析输入...")
    user_input = state["user_query"]

    # 优化：兼容小写 err-503 或带空格的 ERR - 503
    match = re.search(r"err\s*-\s*\d{3}", user_input, re.IGNORECASE)

    if match:
        # 统一格式化为大写且无空格，如 ERR-503
        error_code = match.group(0).replace(" ", "").upper()
    else:
        error_code = "UNKNOWN"

    return {"error_code": error_code}


def retrieve_sop_node(state: AgentState):
    """节点 2：根据提取的特征去检索手册"""
    # 🔥 【核心修复 1】：如果没提取到具体错误码，直接跳过 RAG 检索，防止上下文污染
    if state['error_code'] == "UNKNOWN":
        print("⚠️ 未提取到明确错误码，跳过 RAG 检索，启动兜底逻辑...")
        return {"sop_context": "暂无具体错误码对应的维修手册。"}

    print(f"📌 [节点2] 正在检索手册，错误码: {state['error_code']}...")
    sop = search_manual(state["user_query"])
    return {"sop_context": sop}


def diagnose_node(state: AgentState):
    """节点 3：诊断专家（调用大模型）"""
    print("📌 [节点3] 诊断专家正在生成排障建议...")

    # 🔥 【核心修复 2】：根据是否有错误码，使用不同的强约束 Prompt
    if state['error_code'] == "UNKNOWN":
        prompt = f"""
        你是华大智造的资深售后工程师。
        用户报错：{state['user_query']}

        【系统强制死命令】：
        1. 用户没有提供明确的 ERR 错误码。
        2. 你绝对不可捏造、猜测或提及任何具体的 ERR-xxx 错误码（如 ERR-503）。
        3. 请根据用户的表象描述，提供通用的机械/电气排查建议。
        4. 必须在结尾提醒用户：“为了精准定位，请提供机器屏幕上的具体报错代码（ERR-xxx）。”

        请给出详细的排障建议（字数控制在200字以内）。
        """
    else:
        prompt = f"""
        你是华大智造的资深售后工程师。
        用户报错：{state['user_query']}
        明确错误码：{state['error_code']}
        维修手册：{state['sop_context']}

        请严格依据提供的维修手册，给出详细的排障建议（字数控制在200字以内）。
        """

    response = llm.invoke([HumanMessage(content=prompt)])
    return {"ai_analysis": response.content}


def route_decision_node(state: AgentState):
    """节点 4：规则引擎路由（决定是否高危）"""
    print("📌 [节点4] 规则引擎正在判定红线...")
    HIGH_RISK_CODES = ["ERR-503", "ERR-999"]
    is_high_risk = state["error_code"] in HIGH_RISK_CODES

    if is_high_risk:
        print("🚨 触发企业红线，必须人工审批！")
        return {"final_action": "create_ticket"}
    return {"final_action": "reply"}


def ticket_node(state: AgentState):
    """节点 5：高危工单生成（真实调用 Tool）"""
    print("📌 [节点5] 正在调用发单工具...")
    # 这里模拟调用钉钉/企业微信的 Webhook
    # requests.post("https://oapi.dingtalk.com/robot/send?...", json={"msg": "工单"})
    return {"ai_analysis": state["ai_analysis"]}  # 保持原有的分析文本


# ================= 构建图 =================

workflow = StateGraph(AgentState)

# 注册节点
workflow.add_node("parse", parse_input_node)
workflow.add_node("retrieve", retrieve_sop_node)
workflow.add_node("diagnose", diagnose_node)
workflow.add_node("route", route_decision_node)
workflow.add_node("ticket", ticket_node)

# 编排路由
workflow.set_entry_point("parse")
workflow.add_edge("parse", "retrieve")
workflow.add_edge("retrieve", "diagnose")
workflow.add_edge("diagnose", "route")

# 条件路由：根据 final_action 决定下一步
workflow.add_conditional_edges(
    "route",
    lambda x: x["final_action"],
    {
        "create_ticket": "ticket",
        "reply": END
    }
)
workflow.add_edge("ticket", END)

mgi_agent = workflow.compile()


# ================= 安全调用封装 =================
class TimeoutException(Exception):
    pass


def handler(signum, frame):
    raise TimeoutException("大模型推理超时，已强制阻断以节省Token")


def safe_invoke_agent(inputs, max_time=30):
    """带超时和递归限制的安全调用函数，仅适用于 Linux/WSL"""
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(max_time)

    try:
        # recursion_limit 限制图最多跑 10 步，防止死循环导致无限调模型
        config = {"recursion_limit": 10}
        res = mgi_agent.invoke(inputs, config=config)
        return res
    finally:
        signal.alarm(0)  # 无论成功失败，最终都取消定时器