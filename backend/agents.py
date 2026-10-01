"""Typed, sequential candidate-analysis handoffs.

These are deterministic local agents. Each consumes the previous agent's data and the
resulting trace is stored with the match run.
"""
from typing import Callable, Literal, TypedDict


class Requirement(TypedDict):
    id: int
    label: str
    kind: str
    mandatory: int


class Span(TypedDict):
    id: int
    candidate_id: int
    text: str
    start_offset: int
    end_offset: int


class Assessment(TypedDict):
    requirement_id: int
    label: str
    kind: str
    mandatory: bool
    status: Literal["matched", "partial", "no_evidence", "needs_review"]
    span_id: int | None
    quote: str | None
    reason: str


Evaluator = Callable[[Requirement, list[Span]], tuple[str, Span | None, str | None, str]]


def candidate_matching_agent(requirements: list[Requirement], spans: list[Span], evaluate: Evaluator) -> list[Assessment]:
    assessments = []
    for req in requirements:
        status, span, quote, reason = evaluate(req, spans)
        assessments.append(Assessment(requirement_id=req["id"], label=req["label"], kind=req["kind"],
                                      mandatory=bool(req["mandatory"]), status=status,
                                      span_id=span["id"] if span else None, quote=quote, reason=reason))
    return assessments


def skill_gap_agent(assessments: list[Assessment]) -> list[dict]:
    return [{"label": item["label"], "status": item["status"]}
            for item in assessments if item["kind"] == "skill" and item["status"] != "matched"]


def qualification_agent(assessments: list[Assessment]) -> list[Assessment]:
    return [item for item in assessments if item["kind"] in {"experience", "education", "certification"}]


def explainability_validation_agent(candidate_id: int, assessments: list[Assessment], spans: list[Span]) -> tuple[list[Assessment], list[str]]:
    span_by_id = {span["id"]: span for span in spans if span["candidate_id"] == candidate_id}
    validated = []
    rejected = []
    for original in assessments:
        item = original.copy()
        span = span_by_id.get(item["span_id"])
        if (item["status"] in {"matched", "partial"} or item["quote"]) and (
            not span or not item["quote"] or item["quote"].lower() not in span["text"].lower()
        ):
            item.update(status="needs_review", span_id=None, quote=None, reason="Evidence validation failed.")
            rejected.append(item["label"])
        validated.append(item)
    return validated, rejected
