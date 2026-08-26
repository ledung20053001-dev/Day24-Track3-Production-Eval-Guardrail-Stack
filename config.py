"""Shared configuration for Lab 24: Eval + Guardrail Stack."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
if LLM_PROVIDER not in {"openai", "gemini"}:
    raise ValueError("LLM_PROVIDER must be 'openai' or 'gemini'")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GEMINIKEY", ""))
LLM_API_KEY = GEMINI_API_KEY if LLM_PROVIDER == "gemini" else OPENAI_API_KEY
LLM_BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/"
    if LLM_PROVIDER == "gemini"
    else os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
)
LLM_MODEL = os.getenv(
    "LLM_MODEL",
    "gemini-2.5-flash" if LLM_PROVIDER == "gemini" else "gpt-4o-mini",
)

# RAGAS and NeMo use the OpenAI-compatible environment variables internally.
# Gemini exposes an OpenAI-compatible endpoint, so map the selected provider
# without requiring provider-specific changes in those libraries.
if LLM_API_KEY:
    os.environ["OPENAI_API_KEY"] = LLM_API_KEY
os.environ["OPENAI_BASE_URL"] = LLM_BASE_URL
os.environ["LLM_MODEL"] = LLM_MODEL
HF_TOKEN = os.getenv("HF_TOKEN", "")  # Optional: for HuggingFace models
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() in {"1", "true", "yes"}

# --- Qdrant (same as Day 18) ---
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "lab24_production"

# --- Embedding (same as Day 18) ---
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

# --- Chunking (same as Day 18) ---
HIERARCHICAL_PARENT_SIZE = 2048
HIERARCHICAL_CHILD_SIZE = 256
SEMANTIC_THRESHOLD = 0.85

# --- Search (same as Day 18) ---
BM25_TOP_K = 20
DENSE_TOP_K = 20
HYBRID_TOP_K = 20
RERANK_TOP_K = 3

# --- Paths ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TEST_SET_PATH = os.path.join(os.path.dirname(__file__), "test_set_50q.json")
ANSWERS_PATH = os.path.join(os.path.dirname(__file__), "answers_50q.json")
HUMAN_LABELS_PATH = os.path.join(os.path.dirname(__file__), "human_labels_10q.json")
ADVERSARIAL_SET_PATH = os.path.join(os.path.dirname(__file__), "adversarial_set_20.json")
GUARDRAILS_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "guardrails")

# --- LLM Judge ---
JUDGE_MODEL = LLM_MODEL


def get_llm_client():
    """Return an OpenAI-compatible client for the selected provider."""
    if not LLM_API_KEY:
        raise RuntimeError(f"Missing API key for LLM_PROVIDER={LLM_PROVIDER}")
    from openai import OpenAI
    return OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

# --- Guardrail latency budget ---
LATENCY_BUDGET_P95_MS = 500  # target: full guard stack P95 < 500ms
PRESIDIO_LANGUAGE = "en"    # Presidio base language; custom VN recognizers added via PatternRecognizer
