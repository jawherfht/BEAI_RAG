"""Generate a 50-page benchmark PDF (spec section 12: "Upload -> ready, 50-page PDF <= 2 min").

Each page: a section heading, ~350 words of policy-style prose in short paragraphs, and on
every fifth page a 12-row table. Output: eval/datasets/bench/handbook-50p.pdf
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from make_returns_policy_pdf import build  # noqa: E402

OUT = Path(__file__).parent / "bench" / "handbook-50p.pdf"
WORDS = (
    "employee customer order policy request manager approval period days working hours leave "
    "payment invoice refund shipping warehouse contract notice benefit training safety record "
    "access account support ticket response quality review schedule holiday overtime travel "
    "expense receipt department team office remote equipment security password incident report"
).split()


def sentence(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(9, 16))]
    return " ".join(words).capitalize() + "."


def wrap(text: str, width: int = 92) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [*lines, line] if line else lines


def page(n: int, rng: random.Random) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = [
        ("H", 14, f"Section {n} \u2013 {rng.choice(WORDS).title()} rules")
    ]
    budget = 40 if n % 5 else 22
    while budget > 0:
        para = " ".join(sentence(rng) for _ in range(rng.randint(2, 4)))
        for line in wrap(para):
            out.append(("P", 10, line))
            budget -= 1
        budget -= 1
    if n % 5 == 0:
        out.append(("H", 12, f"Table {n // 5}: limits by category"))
        out.append(("P", 10, "Category            Limit (EUR)     Approval        Notice (days)"))
        for i in range(12):
            out.append(
                (
                    "P",
                    10,
                    f"{rng.choice(WORDS):<20}{rng.randint(50, 5000):<16}"
                    f"{rng.choice(['manager', 'director', 'none']):<16}{rng.randint(1, 30)}",
                )
            )
    return out


def main() -> None:
    rng = random.Random(42)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build([page(n, rng) for n in range(1, 51)]))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
