"""
02a_coding_agent_salt.py
=========================
Coding Agent – uses the CodeInterpreter tool.

Handles queries that require Python code execution, data analysis,
or chart / visualisation generation.

Exports
-------
  CODING_AGENT_NAME_PREFIX  : str
  CODING_AGENT_INSTRUCTIONS : str
  create_agent(agents_client, model, agent_name) -> agent object
"""

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import CodeInterpreterTool

# ── Identity ──────────────────────────────────────────────────────────────
CODING_AGENT_NAME_PREFIX = "CodingAgent"

# ── Instructions ──────────────────────────────────────────────────────────
CODING_AGENT_INSTRUCTIONS = """
You are an expert Python coding assistant with access to a code interpreter.

When given a task:
1. Write clean, well-commented Python code.
2. Execute it using the code_interpreter tool.
3. If the task involves data or statistics, generate a matplotlib visualisation
   (bar chart, pie chart, or the most appropriate type).
4. Save every chart as a PNG file (plt.savefig).
5. After execution, summarise the key findings in plain English.
6. Always show the full code you ran.

Output structure
─────────────────
  CODE:   <the Python code you executed>
  RESULT: <plain-English summary of findings>
  CHART:  <description of the chart that was saved>
""".strip()


# ── Factory ───────────────────────────────────────────────────────────────
def create_agent(agents_client: AgentsClient, model: str, agent_name: str):
    """
    Create and return a coding agent backed by CodeInterpreter.

    Parameters
    ----------
    agents_client : AgentsClient
    model         : deployment name of the chat model
    agent_name    : fully-qualified name including salt, e.g. 'CodingAgent-abc12'
    """
    tool = CodeInterpreterTool()
    agent = agents_client.create_agent(
        model=model,
        name=agent_name,
        instructions=CODING_AGENT_INSTRUCTIONS,
        tools=tool.definitions,
        tool_resources=tool.resources,
    )
    return agent
