import inspect
from pydantic_ai.models.openai import OpenAIChatModel

print(inspect.signature(OpenAIChatModel.__init__))
