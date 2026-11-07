import streamlit as st
import datetime
import random
import time
from agent.graph import safe_invoke_agent
from agent.database import init_db, load_session, save_session, clear_session

st.set_page_config(page_title="MGI 测序仪智能排障", page_icon="🧬", layout="wide")

# 修复下拉框及侧边栏按钮的 CSS
st.markdown("""
<style>
    [data-testid="stHeader"] { display: none !important; }
    .stApp { background: linear-gradient(-45deg, #f0f9ff, #e0f2fe, #f8fafc, #ccfbf1) !important; }
    h1 { color: #1E3A8A !important; font-weight: 800 !important; }
    [data-testid="stAlert"] { background-color: #FEF3C7 !important; border: 1px solid #F59E0B !important; }

    /* 侧边栏背景及文字颜色 */
    [data-testid="stSidebar"] { background-color: #1E293B; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] .stMarkdown { color: #F8FAFC !important; }

    /* 🔥 核心修复：侧边栏按钮的样式（透明质感，字变白） */
    [data-testid="stSidebar"] .stButton > button {
        background-color: transparent !important;
        color: #F8FAFC !important;
        border: 1px solid #475569 !important;
        transition: all 0.3s ease;
    }
    /* 鼠标悬停时的效果（变亮） */
    [data-testid="stSidebar"] .stButton > button:hover {
        background-color: #334155 !important;
        border-color: #94A3B8 !important;
        color: #FFFFFF !important;
    }

    /* 修复下拉框 */
    div[data-testid="stSelectbox"] > div { background-color: #F8FAFC !important; }
    div[data-baseweb="select"] > div { background-color: #F8FAFC !important; border: 1px solid #CBD5E1 !important; }
    div[data-baseweb="select"] div, div[data-baseweb="select"] input, div[data-baseweb="select"] span { color: #1E293B !important; }
    div[data-baseweb="popover"] *, ul[data-testid="stSelectboxVirtualDropdown"] *, ul[role="listbox"] * { color: #1E293B !important; background-color: #FFFFFF !important; }
</style>
""", unsafe_allow_html=True)

# 初始化数据库
init_db()

# ==========================================
# 侧边栏：角色权限(RBAC) 与 架构图
# ==========================================
with st.sidebar:
    st.title("🛡️ 身份与权限")
    user_role = st.selectbox("当前登录身份：", ["👨‍🔬 实验员 (操作员)", "👨‍💼 科室主管 (审批人)"])

    st.divider()
    # 按钮样式已经被上面的 CSS 接管了，现在会变成透明边框风格
    if st.button("🗑️ 清空当前会话并重置", use_container_width=True):
        clear_session()
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.title("🕸️ 系统架构")
    st.caption("LangGraph 多节点协作与条件路由")
    st.markdown("""
    <div style="background-color: #334155; padding: 20px; border-radius: 10px; font-family: monospace; font-size: 14px; line-height: 2;">
        <div style="color: #38BDF8;">[Start] 用户输入</div>
        <div style="color: #64748B; margin-left: 10px;">↓</div>
        <div style="color: #38BDF8;">[Node] 解析 (Parse)</div>
        <div style="color: #64748B; margin-left: 10px;">↓</div>
        <div style="color: #38BDF8;">[Node] 检索 (Retrieve)</div>
        <div style="color: #64748B; margin-left: 10px;">↓</div>
        <div style="color: #38BDF8;">[Node] 诊断 (Diagnose)</div>
        <div style="color: #64748B; margin-left: 10px;">↓</div>
        <div style="color: #F59E0B;">[Router] 规则路由</div>
        <div style="color: #64748B; margin-left: 10px;">↓ (Conditional Edge)</div>
        <div style="display: flex; gap: 20px;">
            <div style="color: #10B981;">→ [End] 常规</div>
            <div style="color: #EF4444;">→ [HITL] 审批 → 工单</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.title("🧬 华大测序仪智能排障 Agent")
st.caption("AI 诊断 + 企业规则双重路由 + 真实工单追踪 (数据持久化版)")

# ==========================================
# 状态初始化 (从数据库恢复)
# ==========================================
if "messages" not in st.session_state:
    saved_data = load_session()
    if saved_data:
        st.session_state.messages = saved_data["messages"]
        st.session_state.awaiting_approval = saved_data["awaiting_approval"]
        st.session_state.ticket_status = saved_data["ticket_status"]
        st.session_state.ticket_data = saved_data["ticket_data"]
    else:
        # 如果没有存档，给默认空值
        st.session_state.messages = []
        st.session_state.awaiting_approval = False
        st.session_state.ticket_status = None
        st.session_state.ticket_data = {}

# 初始化防抖锁
if "is_processing" not in st.session_state:
    st.session_state.is_processing = False

# 渲染历史对话
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# ==========================================
# 输入区与动态执行流
# ==========================================
if not st.session_state.awaiting_approval and st.session_state.ticket_status not in ["维修中", "已结单"]:
    if prompt := st.chat_input("请输入测序仪报错代码或故障描述..."):

        # 【防线】：如果正在处理，拦截一切新请求
        if st.session_state.is_processing:
            st.warning("⚠️ Agent 正在处理上一次请求，请勿重复发送！")
            st.stop()

        st.session_state.is_processing = True  # 上锁
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.status("Agent 多节点协作分析中...", expanded=True) as status:
            st.write("📌 [节点1] 正在解析用户输入...")
            time.sleep(0.4)
            st.write("📌 [节点2] 正在检索维修手册并提取错误码...")
            time.sleep(0.4)

            try:
                # 【防线】：调用带超时机制的安全函数
                res = safe_invoke_agent({"user_query": prompt}, max_time=30)

                error_code = res.get('error_code', 'UNKNOWN')
                st.write(f"✅ 检索完成，锁定错误码：`{error_code}`")
                st.write("📌 [节点3] 诊断专家正在生成排障建议...")
                time.sleep(0.4)
                st.write("📌 [节点4] 规则引擎正在判定企业安全红线...")

                st.session_state.messages.append({"role": "assistant", "content": res["ai_analysis"]})

                if res["final_action"] == "create_ticket":
                    st.write("🚨 **触发高危红线！已挂起，等待人工审批。**")
                    status.update(label="分析完成，等待人工介入", state="complete", expanded=True)
                    st.session_state.awaiting_approval = True
                    st.session_state.ticket_data = {
                        "id": f"MGI-{datetime.datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}",
                        "error": error_code,
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                else:
                    st.write("✅ 常规故障，直接输出建议。")
                    status.update(label="分析完成", state="complete", expanded=False)

            except Exception as e:
                # 捕获超时或异常，保护页面不崩，且防止死循环
                st.error(f"🚨 Agent 执行被强制中断: {str(e)}")
                st.session_state.is_processing = False
                st.stop()

            # 【关键】保存状态到数据库
            save_session(st.session_state.messages, st.session_state.awaiting_approval, st.session_state.ticket_status,
                         st.session_state.ticket_data)

        st.session_state.is_processing = False  # 解锁
        st.rerun()

# ==========================================
# 审批拦截区
# ==========================================
if st.session_state.awaiting_approval:
    st.warning("⚠️ 系统判定该故障触及企业安全红线，必须派发维修工单。")

    if user_role == "👨‍🔬 实验员 (操作员)":
        st.info("🔒 **权限不足**：您的身份为实验员。高危派单操作已提交至主管审批，请等待。")
        if st.button("🔄 刷新状态 (模拟主管已操作)", use_container_width=True):
            st.rerun()
    else:
        st.error("**请主管审批确认！**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 批准派单", type="primary", use_container_width=True):
                st.session_state.awaiting_approval = False
                st.session_state.ticket_status = "维修中"

                t = st.session_state.ticket_data
                ticket_card = f"""
### 🎫 维修工单已生成 (进行中)

| 工单追踪号 | 设备报错 | 审批人 | 派发时间 | 当前状态 |
| :--- | :--- | :--- | :--- | :--- |
| **`{t['id']}`** | `{t['error']}` | 科室主管 | {t['time']} | 🛠️ **工程师维修中** |

> **系统提示**：工单已成功推送至华大智造售后工单池。原厂工程师正在赶来，请保持设备通电。
                """
                st.session_state.messages.append({"role": "assistant", "content": ticket_card})

                # 【关键】保存状态到数据库
                save_session(st.session_state.messages, st.session_state.awaiting_approval,
                             st.session_state.ticket_status, st.session_state.ticket_data)
                st.rerun()

        with col2:
            if st.button("❌ 驳回 (仅自行观察)", use_container_width=True):
                st.session_state.awaiting_approval = False
                st.session_state.messages.append(
                    {"role": "assistant", "content": "🛑 主管已驳回派单。建议按上述 AI 建议自行排查。"})

                # 【关键】保存状态到数据库
                save_session(st.session_state.messages, st.session_state.awaiting_approval,
                             st.session_state.ticket_status, st.session_state.ticket_data)
                st.rerun()

# ==========================================
# 工单状态流转区
# ==========================================
if st.session_state.ticket_status == "维修中":
    st.divider()
    st.success(f"工单 `{st.session_state.ticket_data['id']}` 正在由工程师处理中...")

    if st.button("🧑‍🔧 点击模拟：工程师完成维修并结单", use_container_width=True):
        st.session_state.ticket_status = "已结单"

        close_msg = f"""
### ✅ 工单已闭环结单

| 工单追踪号 | 设备报错 | 结单时间 | 当前状态 |
| :--- | :--- | :--- | :--- |
| **`{st.session_state.ticket_data['id']}`** | `{st.session_state.ticket_data['error']}` | {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | 🟢 **已修复 / 已结单** |

> 设备已恢复正常运行，本次排障流程结束。
        """
        st.session_state.messages.append({"role": "assistant", "content": close_msg})

        # 【关键】保存状态到数据库
        save_session(st.session_state.messages, st.session_state.awaiting_approval, st.session_state.ticket_status,
                     st.session_state.ticket_data)
        st.rerun()