from typing import Generator
from agent_tooling import tool, Agent
from agents.openai import completions_streaming, completions_structured
from pydantic import BaseModel


from models.maker import AgentCode
from utilities.tool_discovery import discover_tools

class AgentMatches(BaseModel):
    agents: list[Agent]
    class Config:
        extra = "forbid"

@tool
def update_agent_code(name: str, update_description: str) -> Generator[str, None, None]:
    """
    Update the code of an agent based on a provided description. This function first checks if the requested agent name matches any available agents. If there's an exact match or similar names are found, it loads the current code of the agent, applies the update description to generate new code, and saves the updated code back to the file system.
    
    Args:
        agent_name (str): The name of the agent whose code needs to be updated.
        update_description (str): A detailed description of what changes need to be made in the agent's code.
        
    Returns:
        Generator[str, None, None]: returns either the updated code, or a message if there wasn't an exact match found.
    """
    from agents.agent_read import get_agent_by_name
    agent = get_agent_by_name(name=name)
    
    
    # Prepare the message based on matches found

    
    code_string = agent.code
    
    # Prepare the update request
    message = f"Update the code of {code_string} based on the following description: {update_description}"
    updated_code = completions_structured(message=message, response_format=AgentCode)

    stream = completions_streaming(
        message=f"Return this code: {updated_code.code} for the agent with the name: {name} along with nicely formatted markdown explaining the code."
    )

    # stream the response
    for chunk in stream:
        yield chunk
    
    # Write the updated code back to the file
    with open(agent.file_path, 'w') as file:
        file.write(updated_code.code)

    # reload the system to get the detail about the edited agent
    discover_tools()
    
    
