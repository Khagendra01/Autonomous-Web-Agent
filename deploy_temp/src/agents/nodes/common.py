"""Shared configuration and clients for node modules."""

from dotenv import load_dotenv
from openai import OpenAI
from ...drivers.grpc_client import DriverClient

# Load environment variables from .env (if present) before initializing OpenAI
load_dotenv()

# Initialize OpenAI client (reads OPENAI_API_KEY from env)
client = OpenAI()

# Initialize gRPC driver client
driver_client = DriverClient()

__all__ = ["client", "driver_client"]


