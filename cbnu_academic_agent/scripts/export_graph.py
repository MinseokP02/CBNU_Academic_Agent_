from pathlib import Path

from app.agent.graph import agent_graph


def main():
    out = Path("workflow.mmd")
    out.write_text(agent_graph.get_graph().draw_mermaid(), encoding="utf-8")
    print(f"saved: {out.resolve()}")


if __name__ == "__main__":
    main()
