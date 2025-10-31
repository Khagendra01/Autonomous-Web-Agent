"""Shared configuration and clients for node modules."""

from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env (if present) before initializing OpenAI
load_dotenv()

# Initialize OpenAI client (reads OPENAI_API_KEY from env)
client = OpenAI()

# Driver API base URL
DRIVER_URL = "http://127.0.0.1:3999"

__all__ = ["client", "DRIVER_URL"]


