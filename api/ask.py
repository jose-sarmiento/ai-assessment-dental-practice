import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from app.agents.retriever import RetrieverAgent

TENANT_ID = "clinic-demo"

PRESET_QUESTIONS = [
    "Show me all appointments for Dr. Reyes in May 2026",
    "What are the morning appointments scheduled for next week?",
    "What appointment is booked by Jane Smith?",
    "Rank appointment types in May 2026 by count from highest to lowest",
    "Who has appointments booked for composite fillings?",
]


def prompt_input() -> str:
    print("Preset questions:")
    for i, q in enumerate(PRESET_QUESTIONS, 1):
        print(f"  {i}. {q}")
    print()

    raw = input("You (enter number or type question): ").strip()

    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(PRESET_QUESTIONS):
            question = PRESET_QUESTIONS[idx]
            print(f"  → {question}")
            return question

    return raw


def main():
    agent = RetrieverAgent(tenant_id=TENANT_ID)
    history = []

    print("\nDental Practice AI — type 'exit' to quit\n")

    while True:
        print()
        query = prompt_input()

        if not query:
            continue
        if query.lower() == "exit":
            break

        history.append({"role": "user", "content": query})

        print("\nAI: ", end="", flush=True)
        stream, citations = agent.run(history)

        answer = ""
        for chunk in stream:
            print(chunk, end="", flush=True)
            answer += chunk

        if citations:
            print(f"\n\nSources: {', '.join(citations)}")
        print()

        history.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
