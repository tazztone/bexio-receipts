import inspect
from pydantic_ai.providers.ollama import OllamaProvider

print(inspect.signature(OllamaProvider.__init__))
