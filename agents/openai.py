import os
import json
from typing import Generator
from openai import OpenAI
from dotenv import load_dotenv
from agent_tooling import tool
from pydantic import BaseModel
from models.open_web_ui import Autocompletion, Tags, Summary

load_dotenv(dotenv_path='secrets.env')
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def completions(message: str, model: str = "gpt-4o") -> str:
    """Call the OpenAI API and return the raw response."""
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "developer", "content": message}
        ]
    )
    content = completion.choices[0].message.content
    return content

def completions_structured(message: str, response_format: BaseModel, model: str = "gpt-4o-2024-08-06") -> BaseModel:
    """Call the OpenAI API and return the raw response."""
    completion = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "developer", "content": message}
        ],
        response_format=response_format
    )
    content = completion.choices[0].message.parsed
    # return the content as the model type
    return content

@tool
def completions_streaming(message: str, model: str = "gpt-4o") -> Generator[str, None, None]:
    """Call the OpenAI API for streaming output."""
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "developer", "content": message}
        ],
        stream=True
    )

    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content
    
#     @tool
# def openai_embeddings(api_key: str, model: str, prompt: str):
#     """Call the OpenAI API for embeddings."""
#     response = openai.Embedding.create(
#         input=prompt,
#         model=model
#     )
#     return response.data