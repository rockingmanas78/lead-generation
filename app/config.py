from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0")
