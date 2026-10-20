"""Ask the agent questions from the terminal.

    python ask.py "How much vacation leave do I earn after 8 years under PA?"
    python ask.py          # chat mode, remembers the conversation; type 'exit' to stop
"""

import sys

from common import ask, cited_files, clients


def show(openai, response) -> None:
    print(f"\n{response.output_text}")
    files = cited_files(openai, response)
    print(f"\n  Sources: {', '.join(files) if files else 'none cited'}\n")


def main() -> None:
    _, openai = clients()

    if len(sys.argv) > 1:
        show(openai, ask(openai, " ".join(sys.argv[1:])))
        return

    conversation = openai.conversations.create()
    print("Ask about the PA, EC or IT agreements. Type 'exit' to stop.\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in {"exit", "quit"}:
            break
        if question:
            show(openai, ask(openai, question, conversation.id))


if __name__ == "__main__":
    main()
