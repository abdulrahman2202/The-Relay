import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

# Load .env from project root
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise RuntimeError("GROQ_API_KEY not found. Check your .env file.")

client = Groq(api_key=api_key)

print("Groq API key loaded successfully!")

# List available models
models = client.models.list()

print("\nAvailable Groq models:\n")

for model in models.data:
    print(model.id)
