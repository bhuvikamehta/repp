import sys
import os
sys.path.append(os.path.abspath('backend'))
import asyncio
from backend.langgraph_agent import build_agent_graph, AgentDeps, compile_agent_graph
from backend.services.gemini_service import GeminiReportingService
from backend.services.db_service import DatabaseService
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async def test():
    gemini = GeminiReportingService()
    db = DatabaseService()
    deps = AgentDeps(gemini=gemini, db=db)
    builder = build_agent_graph(deps=deps)
    
    checkpoint_path = os.path.abspath("backend/backend_checkpoints.sqlite")
    cm = AsyncSqliteSaver.from_conn_string(checkpoint_path)
    checkpointer = await cm.__aenter__()
    
    graph = compile_agent_graph(builder=builder, checkpointer=checkpointer)
    
    update = {"prompt": "Summarize space exploration history."} # NO document key
    
    try:
        state_dict = await graph.ainvoke(
            update,
            config={"configurable": {"thread_id": "test_thread"}},
        )
        print("Success:", state_dict.get("status"))
        if "error" in state_dict and state_dict["error"]:
            print("Error details:", state_dict["error"])
    except Exception as e:
        print("Exception:", str(e))
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
