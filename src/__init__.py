"""AgenticAIOps Package"""

__version__ = "0.1.0"

# Lazy imports to avoid loading heavy dependencies
def get_agent():
    from .agent import AgenticAIOpsAgent, create_agent
    return AgenticAIOpsAgent, create_agent
