import pytest

from app.router.policy import FALLBACK_CLARIFICATION, apply_policy
from app.router.schemas import RouterDecision


def decision(**overrides: object) -> RouterDecision:
    base = {
        "request_type": "code_edit",
        "complexity": "medium",
        "confidence": 0.9,
        "reason": "r",
        "execution_strategy": "plan_execute_review",
        "requires_planning": True,
        "requires_review": True,
    }
    return RouterDecision.model_validate({**base, **overrides})


@pytest.mark.parametrize(
    ("complexity", "strategy", "planning", "review"),
    [
        ("low", "direct", False, False),
        ("medium", "plan_execute_review", True, True),
        ("high", "decompose", True, True),
    ],
)
@pytest.mark.parametrize("mode", ["edit", "auto"])
def test_code_changes_route_to_runs_by_complexity(
    mode: str, complexity: str, strategy: str, planning: bool, review: bool
) -> None:
    plan = apply_policy(decision(complexity=complexity), mode, min_confidence=0.6)  # type: ignore[arg-type]
    assert (plan.route, plan.strategy) == ("run", strategy)
    assert (plan.requires_planning, plan.requires_review) == (planning, review)
    assert not plan.fallback_used


@pytest.mark.parametrize("request_type", ["code_edit", "new_workflow", "question", "clarification"])
def test_ask_mode_never_starts_a_run(request_type: str) -> None:
    plan = apply_policy(decision(request_type=request_type), "ask", min_confidence=0.6)
    assert plan.route == "answer"
    assert plan.request_type == "question"
    if request_type in ("code_edit", "new_workflow"):
        assert plan.policy_note


def test_questions_are_answered_in_every_mode() -> None:
    for mode in ("ask", "edit", "auto"):
        plan = apply_policy(decision(request_type="question"), mode, min_confidence=0.6)  # type: ignore[arg-type]
        assert plan.route == "answer"


def test_model_clarification_is_passed_through() -> None:
    plan = apply_policy(
        decision(request_type="clarification", clarification_question="Which page?"),
        "auto",
        min_confidence=0.6,
    )
    assert (plan.route, plan.clarification_question) == ("clarify", "Which page?")


def test_low_confidence_change_in_auto_mode_asks_first() -> None:
    plan = apply_policy(decision(confidence=0.4), "auto", min_confidence=0.6)
    assert plan.route == "clarify"
    assert plan.clarification_question == FALLBACK_CLARIFICATION
    assert "0.40" in (plan.policy_note or "")


def test_low_confidence_change_in_edit_mode_still_runs() -> None:
    plan = apply_policy(decision(confidence=0.4), "edit", min_confidence=0.6)
    assert plan.route == "run"


def test_policy_overrides_model_strategy_and_says_so() -> None:
    plan = apply_policy(
        decision(complexity="high", execution_strategy="direct"), "edit", min_confidence=0.6
    )
    assert plan.strategy == "decompose"
    assert "decompose" in (plan.policy_note or "")


@pytest.mark.parametrize(
    ("mode", "route"), [("ask", "answer"), ("edit", "run"), ("auto", "clarify")]
)
def test_fallback_when_router_output_is_unusable(mode: str, route: str) -> None:
    plan = apply_policy(None, mode, min_confidence=0.6)  # type: ignore[arg-type]
    assert plan.route == route
    assert plan.fallback_used
    assert plan.confidence is None
    if route == "run":
        assert (plan.complexity, plan.strategy) == ("medium", "plan_execute_review")
