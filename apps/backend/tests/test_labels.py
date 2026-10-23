import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import RoutingLabel
from app.evaluation.labels import (
    agreement,
    cohens_kappa,
    default_split,
    import_labels,
    parse_csv,
)

CSV = """prompt,request_type,complexity
Add a delete button to each todo,code_edit,low
Explain how filtering works,question,low
"Build a todo app with  auth and sync",new_workflow,high
"""


def test_parse_csv_normalizes_and_assigns_stable_splits() -> None:
    labels = parse_csv(CSV)
    assert [label.prompt for label in labels][2] == "Build a todo app with auth and sync"
    assert all(label.split in ("train", "test") for label in labels)
    assert labels[0].split == default_split("Add a delete button to each todo")
    assert default_split("Add  a delete button to each TODO") == labels[0].split


def test_parse_csv_reports_every_bad_row() -> None:
    bad = (
        "prompt,request_type,complexity,split\n"
        ",question,low,train\n"
        "x,refactor,huge,dev\n"
        "x,question,low,\n"
    )
    with pytest.raises(ValueError) as exc:
        parse_csv(bad)
    message = str(exc.value)
    assert "line 2: empty prompt" in message
    assert "line 3: request_type" in message and "line 3: complexity" in message
    assert "line 3: split" in message
    assert "line 4: duplicate prompt" in message


def test_parse_csv_requires_columns() -> None:
    with pytest.raises(ValueError, match="missing columns: complexity"):
        parse_csv("prompt,request_type\nx,question\n")


def test_split_is_roughly_80_20() -> None:
    splits = [default_split(f"prompt number {i}") for i in range(2000)]
    assert 0.15 < splits.count("test") / len(splits) < 0.25


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (["low", "high", "low", "high"], ["low", "high", "low", "high"], 1.0),
        (["low", "high", "low", "high"], ["high", "low", "high", "low"], -1.0),
        (["a", "a", "b", "b"], ["a", "b", "a", "b"], 0.0),
        (["low", "low"], ["low", "low"], None),  # no variation: undefined
        ([], [], None),
    ],
)
def test_cohens_kappa(a: list[str], b: list[str], expected: float | None) -> None:
    result = cohens_kappa(a, b)
    assert result == pytest.approx(expected) if expected is not None else result is None


async def test_import_is_idempotent_and_agreement_uses_shared_prompts(app: FastAPI) -> None:
    other = CSV.replace("question,low", "question,medium") + "Only B labeled this,question,low\n"
    async with app.state.sessionmaker.begin() as session:
        await import_labels(session, parse_csv(CSV), "raghav")
        await import_labels(session, parse_csv(CSV), "raghav")  # re-import replaces
        await import_labels(session, parse_csv(other), "shrey")

    async with app.state.sessionmaker() as session:
        rows = list(await session.scalars(select(RoutingLabel)))
        assert len([r for r in rows if r.labeler == "raghav"]) == 3
        result = await agreement(session, "raghav", "shrey")

    assert result.shared == 3
    assert result.type_raw == 1.0
    assert result.complexity_raw == pytest.approx(2 / 3)
