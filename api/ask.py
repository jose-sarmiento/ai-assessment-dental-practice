import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from app.agents.retriever import RetrieverAgent

TENANT_ID = "clinic-demo"

PRESET_QUESTIONS = {
    "Appointments": [
        "Show me all appointments for Dr. Reyes in May 2026",
        "What are the morning appointments scheduled for next week?",
        "What appointment is booked by Jane Smith?",
        "Rank appointment types in May 2026 by count from highest to lowest",
        "Who has appointments booked for composite fillings?",
    ],
    "Claims": [
        "Show all pending claims",
        "What claims has Jane Smith filed?",
        "Show denied claims and the reason",
        "What is the total amount owed by patients across all claims?",
        "Which insurance payer has the most claims?",
    ],
}


def prompt_input() -> str:
    index = {}
    counter = 1
    for section, questions in PRESET_QUESTIONS.items():
        print(f"{section}:")
        for q in questions:
            print(f"  {counter}. {q}")
            index[counter] = q
            counter += 1
        print()

    raw = input("You (enter number or type question): ").strip()

    if raw.isdigit():
        idx = int(raw)
        if idx in index:
            question = index[idx]
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
        stream, _ = agent.run(history)

        answer = ""
        for chunk in stream:
            print(chunk, end="", flush=True)
            answer += chunk

        print()

        history.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
