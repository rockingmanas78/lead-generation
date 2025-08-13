import tiktoken
from .constants import OPENAI_MODEL


def get_tokenizer():
    try:
        if "gpt-4" in OPENAI_MODEL.lower():
            return tiktoken.encoding_for_model("gpt-4")
        elif "gpt-3.5" in OPENAI_MODEL.lower():
            return tiktoken.encoding_for_model("gpt-3.5-turbo")
        else:
            return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


tokenizer = get_tokenizer()


def count_tokens(text: str) -> int:
    return len(tokenizer.encode(text))
