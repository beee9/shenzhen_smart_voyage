"""入口，对应 a2a_case/main.py。

原案例要先起三个服务（5008 天气、5009 票务、5555 路由 LLM）才能跑；
这里全在一个进程里，直接 python 一下就行。

运行（推荐）：
    cd shenzhen_smart_voyage
    python -m langgraph_case.main

也支持在 IDE 里直接右键运行本文件：下面的 sys.path 兜底会把项目根目录加进来，
再改用绝对导入。
"""

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    # 直接以脚本方式运行（python main.py / IDE 右键运行）时没有父包，
    # 相对导入会失败。把项目根目录塞进 sys.path，改走绝对导入。
    # agent_learn.config 也在项目根下，同样依赖这一步。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from langgraph_case.graph import build_graph
    from langgraph_case.state import read_artifact_text
else:
    from .graph import build_graph
    from .state import read_artifact_text

QUERIES = [
    "帮我查下北京的天气",          # 期望 -> WeatherAgent
    "预订一张从北京到上海的火车票",  # 期望 -> TicketAgent
    "帮我写一首诗",                # 期望 -> Fallback
]


def run_once(app, query: str) -> None:
    """跑一次完整流程，打印结果。"""
    print("=" * 60)
    print(f"[主控日志] 用户查询: '{query}'")

    # invoke 的入参就是初始 state。带累加器的 logs 要给初始值 []，
    # 否则第一个节点的 operator.add 没有左操作数。
    final_state = app.invoke({
        "query": query,
        "agent_name": "",
        "confidence": 0.0,
        "artifacts": [],
        "status": "",
        "logs": [],
    })

    print("-" * 60)
    print(f"[主控日志] 路由到: {final_state['agent_name']} "
          f"(置信度 {final_state['confidence']})")
    print(f"[主控日志] 任务状态: {final_state['status']}")
    print(f"[主控日志] 最终结果: {read_artifact_text(final_state['artifacts'])}")
    print("[主控日志] 完整 artifacts:")
    print(json.dumps(final_state["artifacts"], indent=4, ensure_ascii=False))
    print("[主控日志] 执行轨迹:")
    for i, line in enumerate(final_state["logs"], 1):
        print(f"    {i}. {line}")
    print()


def main() -> None:
    app = build_graph()
    print("[主控日志] 图编译完成，结构如下：")
    try:
        print(app.get_graph().draw_ascii())
    except Exception:
        # draw_ascii 需要 grandalf，没装就跳过，不影响主流程
        print("    (装 grandalf 可以看到 ASCII 图: pip install grandalf)")
    print()

    for query in QUERIES:
        run_once(app, query)


if __name__ == "__main__":
    main()
