"""Deterministic routing policy (plan §3.1). The Router model proposes; this decides.

Initial heuristics, to be tuned with M7 evaluation data:
- low    -> direct Coder, review only if checks fail
- medium -> plan -> execute -> review
- high   -> decompose -> parallel execute -> review
"""

from app.router.schemas import Complexity, Mode, RoutePlan, RouterDecision, Strategy

STRATEGY_BY_COMPLEXITY: dict[Complexity, Strategy] = {
    "low": "direct",
    "medium": "plan_execute_review",
    "high": "decompose",
}

FALLBACK_CLARIFICATION = (
    "I couldn't tell whether you want an answer or a code change. "
    "Could you say which files or behaviour you want changed, or switch to Ask or Edit mode?"
)


def _run_plan(complexity: Complexity, **kwargs: object) -> RoutePlan:
    strategy = STRATEGY_BY_COMPLEXITY[complexity]
    return RoutePlan(
        route="run",
        complexity=complexity,
        strategy=strategy,
        requires_planning=strategy != "direct",
        requires_review=strategy != "direct",
        **kwargs,  # type: ignore[arg-type]
    )


def apply_policy(
    decision: RouterDecision | None, mode: Mode, *, min_confidence: float
) -> RoutePlan:
    # 1. Unusable model output: conservative deterministic fallback.
    if decision is None:
        if mode == "ask":
            return RoutePlan(
                route="answer",
                request_type="question",
                complexity="medium",
                confidence=None,
                reason="Router output invalid; Ask mode answers without editing.",
                fallback_used=True,
            )
        if mode == "edit":
            return _run_plan(
                "medium",
                request_type="code_edit",
                confidence=None,
                reason="Router output invalid; Edit mode uses the conservative medium route.",
                fallback_used=True,
            )
        return RoutePlan(
            route="clarify",
            request_type="clarification",
            complexity="medium",
            confidence=None,
            clarification_question=FALLBACK_CLARIFICATION,
            reason="Router output invalid; Auto mode asks instead of guessing.",
            fallback_used=True,
        )

    common = {"confidence": decision.confidence, "reason": decision.reason}
    wants_change = decision.request_type in ("code_edit", "new_workflow")

    # 2. Ask mode never writes, whatever the model says.
    if mode == "ask":
        note = "Ask mode: answered without editing." if wants_change else None
        return RoutePlan(
            route="answer",
            request_type="question",
            complexity=decision.complexity,
            policy_note=note,
            **common,
        )

    # 3. The model asked for clarification.
    if decision.request_type == "clarification":
        return RoutePlan(
            route="clarify",
            request_type="clarification",
            complexity=decision.complexity,
            clarification_question=decision.clarification_question or FALLBACK_CLARIFICATION,
            **common,
        )

    # 4. Questions are answered in any mode.
    if decision.request_type == "question":
        return RoutePlan(
            route="answer", request_type="question", complexity=decision.complexity, **common
        )

    # 5. Code changes. Auto mode needs enough confidence; Edit mode is explicit consent.
    if mode == "auto" and decision.confidence < min_confidence:
        return RoutePlan(
            route="clarify",
            request_type="clarification",
            complexity=decision.complexity,
            clarification_question=decision.clarification_question or FALLBACK_CLARIFICATION,
            policy_note=(
                f"Confidence {decision.confidence:.2f} < {min_confidence:.2f} in Auto mode."
            ),
            **common,
        )

    plan = _run_plan(decision.complexity, request_type=decision.request_type, **common)
    if decision.execution_strategy != plan.strategy:
        plan.policy_note = (
            f"Model proposed '{decision.execution_strategy}'; policy uses '{plan.strategy}' "
            f"for {decision.complexity} complexity."
        )
    return plan
