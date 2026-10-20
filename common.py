"""Shared setup used by the other scripts: settings from .env, clients for the
Foundry project, and helpers for asking the agent and reading its citations."""

import os
import pathlib
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

VECTOR_STORE_NAME = "gc-agreements"


def setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return value


def agent_name() -> str:
    return os.getenv("AGENT_NAME", "gc-pay-agent")


def clients():
    """Project client (manages agents) and OpenAI client (files, vector stores, responses).
    Signs in with your `az login` session."""
    project = AIProjectClient(endpoint=setting("PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    return project, project.get_openai_client()


def find_vector_store(openai, name: str):
    for store in openai.vector_stores.list():
        if store.name == name:
            return store
    return None


def ask(openai, question: str, conversation_id: str | None = None):
    """Send one question to the agent. Pass a conversation ID to keep chat history."""
    kwargs = {
        "input": question,
        "extra_body": {"agent_reference": {"name": agent_name(), "type": "agent_reference"}},
    }
    if conversation_id:
        kwargs["conversation"] = conversation_id
    return openai.responses.create(**kwargs)


def cited_files(openai, response) -> list[str]:
    """Names of the documents the answer cited, in order, without duplicates."""
    names: list[str] = []
    file_names: dict[str, str] = {}
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            for note in getattr(part, "annotations", None) or []:
                if getattr(note, "type", None) != "file_citation":
                    continue
                name = getattr(note, "filename", None)
                if not name:
                    file_id = note.file_id
                    if file_id not in file_names:
                        try:
                            file_names[file_id] = openai.files.retrieve(file_id).filename
                        except Exception:
                            file_names[file_id] = file_id
                    name = file_names[file_id]
                if name not in names:
                    names.append(name)
    return names
