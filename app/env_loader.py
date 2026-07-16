"""
env_loader.py

Purpose: automatically loads variables from a .env file in the project
root into the environment, so you don't need to manually 'export' them
in every new terminal.

Every other file that needs an env variable (GROQ_API_KEY, GMAIL_ADDRESS,
etc.) imports this FIRST, before reading any environment variable.
"""

import os
from dotenv import load_dotenv

# .env is expected in the project root, one level up from app/
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(ENV_PATH)
