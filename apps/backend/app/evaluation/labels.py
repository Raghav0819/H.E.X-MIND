"""Routing label set for the scikit-learn baseline vs. LLM Router comparison (plan §9 M2/M7).

Labels come from people (see docs/routing-labels.md), never from a model. CSV columns:
`prompt,request_type,complexity` and optionally `split` (train|test). Without a split, each
prompt is assigned one deterministically from its text, so every labeler's copy of the same
prompt lands in the same split.

Usage:
    python -m app.evaluation.labels import <file.csv> --labeler <name>
    python -m app.evaluation.labels agreement <labeler_a> <labeler_b>
    python -m app.evaluation.labels stats
"""

import argparse
import asyncio
import csv
import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import RoutingLabel
from app.db.session import create_engine, create_sessionmaker
from app.router.schemas import Complexity, RequestType

REQUEST_TYPES = set(get_args(RequestType))
COMPLEXITIES = set(get_args(Complexity))
TEST_FRACTION = 0.2


@dataclass(frozen=True)
class Label:
    prompt: str
    request_type: str
    complexity: str
    split: str


def normalize_prompt(prompt: str) -> str:
    return " ".join(prompt.split())


def default_split(prompt: str) -> str:
    digest = hashlib.sha256(normalize_prompt(prompt).lower().encode()).digest()
    return "test" if digest[0] / 256 < TEST_FRACTION else "train"


def parse_csv(text: str) -> list[Label]:
    """Parse and validate a label file; raises ValueError listing every bad row."""
    reader = csv.DictReader(text.splitlines())
    missing = {"prompt", "request_type", "complexity"} - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"missing columns: {', '.join(sorted(missing))}")

    labels: list[Label] = []
    errors: list[str] = []
    seen: set[str] = set()
    for line, row in enumerate(reader, start=2):
        prompt = normalize_prompt(row.get("prompt") or "")
        request_type = (row.get("request_type") or "").strip()
        complexity = (row.get("complexity") or "").strip()
        split = (row.get("split") or "").strip() or default_split(prompt)
        if not prompt:
            errors.append(f"line {line}: empty prompt")
        elif prompt.lower() in seen:
            errors.append(f"line {line}: duplicate prompt")
        if request_type not in REQUEST_TYPES:
            errors.append(f"line {line}: request_type must be one of {sorted(REQUEST_TYPES)}")
        if complexity not in COMPLEXITIES:
            errors.append(f"line {line}: complexity must be one of {sorted(COMPLEXITIES)}")
        if split not in ("train", "test"):
            errors.append(f"line {line}: split must be train or test")
        seen.add(prompt.lower())
        labels.append(Label(prompt, request_type, complexity, split))
    if errors:
        raise ValueError("\n".join(errors))
    return labels


async def import_labels(session: AsyncSession, labels: list[Label], labeler: str) -> int:
    """Replace this labeler's labels for the given prompts (re-importing a file is idempotent)."""
    prompts = [label.prompt for label in labels]
    await session.execute(
        delete(RoutingLabel).where(
            RoutingLabel.labeler == labeler, RoutingLabel.prompt.in_(prompts)
        )
    )
    session.add_all(
        RoutingLabel(
            prompt=label.prompt,
            label_type=label.request_type,
            label_complexity=label.complexity,
            labeler=labeler,
            split=label.split,
        )
        for label in labels
    )
    return len(labels)


def cohens_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa for two raters over the same items; None when undefined."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[k] * count_b[k] for k in count_a.keys() | count_b.keys()) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


@dataclass(frozen=True)
class Agreement:
    shared: int
    complexity_kappa: float | None
    type_kappa: float | None
    complexity_raw: float | None
    type_raw: float | None


async def agreement(session: AsyncSession, labeler_a: str, labeler_b: str) -> Agreement:
    rows = list(
        await session.scalars(
            select(RoutingLabel).where(RoutingLabel.labeler.in_([labeler_a, labeler_b]))
        )
    )
    by_prompt: dict[str, dict[str, RoutingLabel]] = {}
    for row in rows:
        by_prompt.setdefault(row.prompt.lower(), {})[row.labeler] = row
    pairs = [(v[labeler_a], v[labeler_b]) for v in by_prompt.values() if len(v) == 2]
    if not pairs:
        return Agreement(0, None, None, None, None)
    comp_a, comp_b = [p[0].label_complexity for p in pairs], [p[1].label_complexity for p in pairs]
    type_a, type_b = [p[0].label_type for p in pairs], [p[1].label_type for p in pairs]
    return Agreement(
        shared=len(pairs),
        complexity_kappa=cohens_kappa(comp_a, comp_b),
        type_kappa=cohens_kappa(type_a, type_b),
        complexity_raw=sum(x == y for x, y in zip(comp_a, comp_b, strict=True)) / len(pairs),
        type_raw=sum(x == y for x, y in zip(type_a, type_b, strict=True)) / len(pairs),
    )


async def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.labels")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import")
    imp.add_argument("file", type=Path)
    imp.add_argument("--labeler", required=True)
    agree = commands.add_parser("agreement")
    agree.add_argument("labeler_a")
    agree.add_argument("labeler_b")
    commands.add_parser("stats")
    args = parser.parse_args(argv)

    engine = create_engine(get_settings().database_url)
    sessionmaker = create_sessionmaker(engine)
    try:
        async with sessionmaker.begin() as session:
            if args.command == "import":
                labels = parse_csv(args.file.read_text(encoding="utf-8-sig"))
                count = await import_labels(session, labels, args.labeler)
                print(f"imported {count} labels for {args.labeler}")
            elif args.command == "agreement":
                result = await agreement(session, args.labeler_a, args.labeler_b)
                print(result)
            else:
                rows = list(await session.scalars(select(RoutingLabel)))
                print(f"{len(rows)} labels")
                for key in ("labeler", "split", "label_type", "label_complexity"):
                    print(f"  {key}: {dict(Counter(getattr(r, key) for r in rows))}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
