"""Create or update the agent.

Uploads the agreements in ./docs to a vector store (the agent's built-in file
search), then publishes a new agent version using the instructions in
agent/instructions.md. Run it again whenever you change the instructions:
each run creates a new version, so you can compare versions later.

    python create_agent.py            # reuse documents already uploaded
    python create_agent.py --reload   # replace the documents (after re-running get_agreements.py)
"""

import argparse
import sys

from azure.ai.projects.models import FileSearchTool, PromptAgentDefinition

from common import ROOT, VECTOR_STORE_NAME, agent_name, clients, find_vector_store, setting

DOCS_DIR = ROOT / "docs"
INSTRUCTIONS = ROOT / "agent" / "instructions.md"


def load_documents(openai, reload: bool):
    existing = find_vector_store(openai, VECTOR_STORE_NAME)
    if existing and not reload:
        print(f"Reusing uploaded documents (vector store {existing.id}).")
        return existing

    if existing:
        for doc in openai.vector_stores.files.list(vector_store_id=existing.id):
            openai.files.delete(doc.id)
        openai.vector_stores.delete(existing.id)
        print(f"Removed old documents (vector store {existing.id}).")

    paths = sorted(DOCS_DIR.glob("*.html"))
    if not paths:
        sys.exit("No documents in docs/. Run get_agreements.py first.")

    store = openai.vector_stores.create(name=VECTOR_STORE_NAME)
    for path in paths:
        with path.open("rb") as handle:
            result = openai.vector_stores.files.upload_and_poll(vector_store_id=store.id, file=handle)
        if result.status != "completed":
            sys.exit(f"Upload failed for {path.name}: {result.last_error}")
        print(f"Uploaded {path.name}")
    return store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reload", action="store_true", help="replace the uploaded documents")
    args = parser.parse_args()

    project, openai = clients()
    store = load_documents(openai, args.reload)

    agent = project.agents.create_version(
        agent_name=agent_name(),
        definition=PromptAgentDefinition(
            model=setting("MODEL_DEPLOYMENT"),
            instructions=INSTRUCTIONS.read_text(encoding="utf-8"),
            tools=[FileSearchTool(vector_store_ids=[store.id])],
        ),
        description="Answers questions about GC collective agreements (PA, EC, IT) with citations.",
    )
    print(f"\nAgent '{agent.name}' is now at version {agent.version}.")
    print('Try it: python ask.py "How much vacation leave do I earn after 8 years under PA?"')


if __name__ == "__main__":
    main()
