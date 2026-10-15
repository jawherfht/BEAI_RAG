import pytest

from worker.chunking.sentences import split_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("One. Two! Three?", ["One.", "Two!", "Three?"]),
        ("See e.g. the policy. Next one.", ["See e.g. the policy.", "Next one."]),
        ("Call J. Smith today. Thanks.", ["Call J. Smith today.", "Thanks."]),
        ("Read Section 4. It says more.", ["Read Section 4. It says more."]),
        ("Line one\nLine two", ["Line one", "Line two"]),
        ("Bonjour. Ça va ? Oui.", ["Bonjour.", "Ça va ?", "Oui."]),
        ("هل لديك سياسة إرجاع؟ نعم، ثلاثون يوماً.", ["هل لديك سياسة إرجاع؟", "نعم، ثلاثون يوماً."]),
        ("第一句。第二句！", ["第一句。第二句！"]),
        ('He said "stop." Then left.', ['He said "stop."', "Then left."]),
    ],
)
def test_split(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected
