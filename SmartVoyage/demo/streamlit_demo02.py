import streamlit as st

# 页面配置
st.set_page_config(page_title="我的应用", layout="wide")

# 标题和文字
st.title("标题")
st.markdown("**加粗文字**")

# 侧边栏
with st.sidebar:
    st.markdown("### 设置")
    name = st.text_input("你的名字")

# 按钮
if st.button("点击我"):
    st.success(f"你好，{name}！")

# 表格
st.table([{"name": "Alice", "age": 25}])

# 聊天消息
with st.chat_message("user"):
    st.markdown("用户说的话")

with st.chat_message("assistant"):
    st.markdown("助手回复")


# 缓存数据（避免重复请求）
@st.cache_data(ttl=5)
def fetch_data():
    return {"key": "value"}


st.write(fetch_data())

# 状态持久化（刷新页面不丢失）
if "counter" not in st.session_state:
    st.session_state.counter = 0

# 输入框（chat_input 必须放在最后，Streamlit 要求它是页面的最后一个元素）
msg = st.chat_input("输入消息...")
if msg:
    st.write(f"你说了：{msg}")
