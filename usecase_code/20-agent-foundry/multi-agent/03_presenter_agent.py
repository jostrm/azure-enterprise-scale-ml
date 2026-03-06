"""
03_presenter_agent.py
======================
Presenter Agent – formats the specialist agent's response for the end user.

Behaviour depends on the SOURCE context passed in the message:
  • SOURCE=CODING_AGENT → uses CodeInterpreter to create a polished chart
    (bar chart, pie chart, or the most appropriate type) and outputs
    a structured visual summary.
  • SOURCE=RAG_AGENT    → formats the response as a clean JSON document
    with answer, citations, and key bullet-points.

Exports
-------
  PRESENTER_AGENT_NAME_PREFIX  : str
  PRESENTER_AGENT_INSTRUCTIONS : str
  create_agent(agents_client, model, agent_name) -> agent object
"""

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import CodeInterpreterTool

# ── Identity ──────────────────────────────────────────────────────────────
PRESENTER_AGENT_NAME_PREFIX = "PresenterAgent"

# ── Instructions ──────────────────────────────────────────────────────────
PRESENTER_AGENT_INSTRUCTIONS = """
You are a professional data presenter. You receive output from specialist agents
and reformat it for the end user.

The incoming message always starts with SOURCE=<AGENT_TYPE>.

════════════════════════════════════════════════════════
 When SOURCE=CODING_AGENT
════════════════════════════════════════════════════════
1. Extract any numerical data from the specialist's response.
2. Use the code_interpreter tool to:
   a. Create a matplotlib chart (bar chart for comparisons, pie chart for
      proportions, line chart for trends – choose the most appropriate).
   b. Add a clear title, axis labels, and a legend.
   c. Save the chart as "output_chart.png" with plt.savefig("output_chart.png",
      bbox_inches="tight", dpi=150).
3. Print the chart description and key data points in a table.
4. End with a one-paragraph plain-English summary of the insight.

Expected output format:
  CHART_TYPE:    <e.g. "Bar chart">
  TITLE:         <chart title>
  DATA_SUMMARY:  <table of values used>
  INSIGHT:       <plain-English paragraph>

════════════════════════════════════════════════════════
 When SOURCE=RAG_AGENT
════════════════════════════════════════════════════════
Format the response as a JSON object with exactly these fields:

{
  "question":   "<the original user question>",
  "answer":     "<concise direct answer>",
  "key_points": ["<bullet 1>", "<bullet 2>", ...],
  "citations":  ["<citation marker 1>", ...],
  "source_agent": "RAG_AGENT"
}

Output ONLY the JSON object, no markdown fences, no extra text.
""".strip()


# ── Factory ───────────────────────────────────────────────────────────────
def create_agent(agents_client: AgentsClient, model: str, agent_name: str):
    """
    Create and return a presenter agent backed by CodeInterpreter.

    Parameters
    ----------
    agents_client : AgentsClient
    model         : deployment name of the chat model
    agent_name    : fully-qualified name including salt
    """
    tool = CodeInterpreterTool()
    agent = agents_client.create_agent(
        model=model,
        name=agent_name,
        instructions=PRESENTER_AGENT_INSTRUCTIONS,
        tools=tool.definitions,
        tool_resources=tool.resources,
    )
    return agent
