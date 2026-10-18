"""
SmartVoyage 前端控制台
运行: streamlit run streamlit_app.py
依赖: pip install streamlit requests
"""
import json
import time

import requests
import streamlit as st

# ==================== 配置 ====================
API_BASE = "http://127.0.0.1:8088"
CHAT_TIMEOUT = 180
QUICK_TIMEOUT = 30

st.set_page_config(
    page_title="SmartVoyage 控制台",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded")

# ==================== 样式 ====================
st.markdown("""
<style>
  .block-container { padding-top: 2.2rem; padding-bottom: 1rem; max-width: 1180px; }
  .sv-hero { display: flex; align-items: baseline; gap: .7rem; margin-bottom: .2rem; }
  .sv-hero h1 { font-size: 1.65rem; margin: 0; letter-spacing: -.01em; }
  div[data-testid="stMetric"] {
      background: rgba(128,128,128,.06);
      border: 1px solid rgba(128,128,128,.16);
      border-radius: 12px;
      padding: .7rem .9rem;
  }
  div[data-testid="stChatMessage"] {
      border-radius: 14px;
      padding: .85rem 1rem;
      margin-bottom: .5rem;
      background: rgba(128,128,128,.06);
  }
</style>
""", unsafe_allow_html=True)

# ==================== API 封装 ====================

def api_get(path: str):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=QUICK_TIMEOUT)
    except Exception as e:
        return False, f"连不上 {API_BASE}（{type(e).__name__}）"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    return True, r.json()


def api_post(path: str, payload: dict = None, timeout: int = QUICK_TIMEOUT):
    try:
        r = requests.post(f"{API_BASE}{path}", json=payload, timeout=timeout)
    except Exception as e:
        return False, f"请求失败（{type(e).__name__}）"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    return True, r.json()


def stream_chat(message: str):
    try:
        r = requests.post(
            f"{API_BASE}/api/chat/stream",
            json={"message": message},
            timeout=CHAT_TIMEOUT,
            stream=True)
    except Exception as e:
        yield f"请求失败（{type(e).__name__}）"
        return
    if r.status_code != 200:
        yield f"请求失败（HTTP {r.status_code}）"
        return

    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        raw = line[len("data: "):]
        if raw == "[DONE]":
            break
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "error" in obj:
            yield f"服务端报错：{obj['error']}"
            return
        if obj.get("content"):
            yield obj["content"]


# ==================== 缓存 & 刷新 ====================

@st.cache_data(ttl=5, show_spinner=False)
def fetch_agents():
    return api_get("/api/agents")


@st.cache_data(ttl=5, show_spinner=False)
def fetch_memory():
    return api_get("/api/memory")


def refresh():
    fetch_agents.clear()
    fetch_memory.clear()
    st.rerun()


# ==================== 侧边栏 ====================

def render_sidebar():
    with st.sidebar:
        st.markdown("### ⚙️ 设置")
        stream_on = st.toggle("流式响应（SSE）", value=True,
                              help="开：逐片段返回；关：等完整回复")
        st.divider()

        # 子代理状态
        st.markdown("### 🛰 子代理")
        ok, body = fetch_agents()
        if not ok:
            st.error(body)
        else:
            agents = body.get("data", [])
            for a in agents:
                flag = "🟢" if a.get("reachable") else "🔴"
                with st.expander(f"{flag} {a.get('name')}", expanded=False):
                    st.caption(a.get("description") or "")
                    for s in a.get("skills", []):
                        st.markdown(f"**{s.get('name')}**")
                        for ex in (s.get("examples") or [])[:2]:
                            st.markdown(f"<span style='color:gray;font-size:0.85em'>例：{ex}</span>",
                                        unsafe_allow_html=True)
                    st.caption(f"{a.get('url')} · v{a.get('version')}")
                    if a.get("error"):
                        st.caption(f"⚠️ {a['error']}")

        if st.button("刷新代理状态", use_container_width=True):
            refresh()

        st.divider()
        render_profile_editor()
        st.divider()
        render_danger_zone()

    return stream_on


def render_profile_editor():
    st.markdown("### 🎛 用户偏好")
    ok, body = fetch_memory()
    profile = body.get("data", {}).get("user_profile", {}) if ok else {}
    rows = [{"偏好项": k, "取值": v} for k, v in profile.items()]
    if not rows:
        rows = [{"偏好项": "", "取值": ""}]

    edited = st.data_editor(
        rows, num_rows="dynamic", hide_index=True,
        use_container_width=True, key="profile_editor",
        column_config={
            "偏好项": st.column_config.TextColumn(width="small"),
            "取值": st.column_config.TextColumn(width="small"),
        },)

    if st.button("保存偏好", use_container_width=True, type="primary"):
        payload = {
            r["偏好项"].strip(): r["取值"].strip()
            for r in edited
            if (r.get("偏好项") or "").strip() and (r.get("取值") or "").strip()}
        if not payload:
            st.warning("没有可保存的内容")
        else:
            ok, body = api_post("/api/memory/profile", {"profile": payload})
            if ok:
                st.success(body.get("message", "已保存"))
                refresh()
            else:
                st.error(body)

    st.markdown("<span style='color:gray;font-size:0.8em'>后端是增量更新（dict.update），"
                "删行不会删掉后端已有的键；要真清空请用下方「清空记忆」。</span>",
                unsafe_allow_html=True)


def render_danger_zone():
    st.markdown("### 🧹 清空记忆")
    st.markdown("<span style='color:gray;font-size:0.8em'>短期对话、偏好、任务上下文、查询历史全部删除。</span>",
                unsafe_allow_html=True)
    sure = st.checkbox("我确认要清空")
    if st.button("清空记忆", use_container_width=True, disabled=not sure):
        ok, body = api_post("/api/memory/clear")
        if ok:
            st.session_state.messages = []
            st.toast(body.get("message", "记忆已清空"), icon="🧹")
            refresh()
        else:
            st.error(body)


# ==================== 主区顶部 ====================

def render_header(stream_on: bool):
    st.markdown("<div class='sv-hero'><h1>🧭 SmartVoyage 控制台</h1>"
                "<span>A2A + MCP 多智能体旅行助手</span></div>",
                unsafe_allow_html=True,)
    ok_a, body_a = fetch_agents()
    ok_m, body_m = fetch_memory()
    if not ok_a:
        st.error(f"后端不可用：{body_a}　请先启动 api_server.py")
        st.stop()

    agents = body_a.get("data", [])
    online = sum(1 for a in agents if a.get("reachable"))
    mem = body_m.get("data", {}) if ok_m else {}

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("子代理在线", f"{online} / {len(agents)}")
    c2.metric("响应模式", "流式 SSE" if stream_on else "非流式")
    c3.metric("短期对话", len(mem.get("short_term_messages", [])))
    c4.metric("查询历史", len(mem.get("entity_history", [])))

    if online < len(agents):
        down = [a.get("name") for a in agents if not a.get("reachable")]
        st.warning(f"这些子代理没起来：{'、'.join(map(str, down))}")


# ==================== 聊天区 ====================

EXAMPLES = [
    "成都明天天气怎么样",
    "北京到成都 2026-05-01 的火车票",
    "推荐去稻城亚丁的旅游团",
]


def render_chat(stream_on: bool):
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if not st.session_state.messages:
        st.markdown("<span style='color:gray;font-size:0.9em'>试试这些问题：</span>",
                    unsafe_allow_html=True)
        cols = st.columns(len(EXAMPLES))
        for col, ex in zip(cols, EXAMPLES):
            if col.button(ex, use_container_width=True, key=f"ex_{ex}"):
                st.session_state.pending = ex
                st.rerun()

    for msg in st.session_state.messages:
        avatar = "🧑" if msg["role"] == "user" else "🧭"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("meta"):
                st.caption(msg["meta"])

    typed = st.chat_input("问点什么，比如「成都明天天气」……")
    text = typed or st.session_state.pop("pending", None)
    if not text:
        return

    # 特殊指令：清空
    if text.strip().lower() == "清空":
        ok, body = api_post("/api/memory/clear")
        if ok:
            st.session_state.messages = []
            st.toast(body.get("message", "记忆已清空"), icon="🧹")
            refresh()
        else:
            st.error(body)
        return

    st.session_state.messages.append({"role": "user", "content": text})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(text)

    with st.chat_message("assistant", avatar="🧭"):
        t0 = time.time()
        if stream_on:
            reply = st.write_stream(stream_chat(text))
            mode = "流式 SSE"
        else:
            with st.spinner("思考中……（走完整 Agent 链路，要几十秒）"):
                ok, body = api_post("/api/chat", {"message": text}, timeout=CHAT_TIMEOUT)
            reply = body.get("message", "（未收到回复）") if ok else f"❌ {body}"
            st.markdown(reply)
            mode = "非流式"
        meta = f"{mode} · {time.time() - t0:.1f}s"
        st.caption(meta)

    st.session_state.messages.append({
        "role": "assistant", "content": reply or "（未收到回复）", "meta": meta,
    })
    fetch_memory.clear()
    st.rerun()


# ==================== 记忆面板 ====================

def render_memory_panel():
    ok, body = fetch_memory()
    if not ok:
        st.error(f"读取记忆失败：{body}")
        return

    m = body.get("data", {})
    msgs = m.get("short_term_messages", [])
    profile = m.get("user_profile", {})
    task = m.get("current_task", {})
    entities = m.get("entity_history", [])

    t1, t2, t3, t4 = st.tabs([
        f"💬 短期对话 {len(msgs)}",
        f"🎛 偏好 {len(profile)}",
        f"📌 当前任务 {len(task)}",
        f"🕘 查询历史 {len(entities)}",
    ])

    with t1:
        if not msgs:
            st.caption("无")
        for x in msgs:
            who = "🧑 user" if x.get("role") == "user" else "🧭 assistant"
            st.markdown(f"**{who}** · `{x.get('timestamp', '')}`")
            st.markdown(x.get("content", ""))
            st.divider()

    with t2:
        if profile:
            st.table([{"偏好项": k, "取值": v} for k, v in profile.items()])
        else:
            st.caption("无。可在左侧「用户偏好」里添加。")

    with t3:
        if task:
            st.table([{"字段": k, "值": v} for k, v in task.items()])
        else:
            st.caption("无。查过票或旅游团之后这里会记录当前任务上下文。")

    with t4:
        if not entities:
            st.caption("无")
        for e in reversed(entities):
            st.markdown(f"`{e.get('type')}` · {e.get('query')}")
            st.caption(e.get("timestamp", ""))


# ==================== 主入口 ====================

def main():
    stream_on = render_sidebar()

    left, right = st.columns([3, 2])
    with left:
        render_header(stream_on)
        st.divider()
        render_chat(stream_on)

    with right:
        st.markdown("### 🧠 记忆面板")
        render_memory_panel()


if __name__ == "__main__":
    main()




