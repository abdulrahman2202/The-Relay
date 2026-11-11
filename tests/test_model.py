import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

client = Groq(api_key=os.environ["GROQ_API_KEY"])
model = os.environ["GROQ_MODEL"]

response = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Explain the Transformer architecture in 3 sentences."}],
    temperature=0.2,
    max_completion_tokens=200,
)

print("Model:", model)
print("Response:", response.choices[0].message.content)
print("Input tokens:", response.usage.prompt_tokens)
print("Output tokens:", response.usage.completion_tokens)
