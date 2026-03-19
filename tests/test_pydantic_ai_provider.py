import inspect
from pydantic_ai.providers.openai import OpenAIProvider

print(inspect.signature(OpenAIProvider.__init__))
