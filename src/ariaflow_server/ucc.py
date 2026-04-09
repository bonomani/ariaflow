from __future__ import annotations


def ucc_envelope(
    *,
    target: str,
    observed: bool,
    outcome: str,
    completion: str | None = None,
    reason: str = "aggregate",
    detail: str | None = None,
    commands: list[str] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "observation": "ok" if observed else "failed",
        "outcome": outcome,
        "reason": reason,
        "target": target,
    }
    if completion is not None:
        result["completion"] = completion
    if detail is not None:
        result["message"] = detail
    if commands is not None:
        result["commands"] = commands
    return {
        "meta": {"contract": "UCC", "version": "2.0", "target": target},
        "result": result,
    }


def ucc_record(
    *,
    target: str,
    observed: bool,
    outcome: str,
    completion: str | None = None,
    reason: str = "aggregate",
    detail: str | None = None,
    commands: list[str] | None = None,
) -> dict[str, object]:
    return ucc_envelope(
        target=target,
        observed=observed,
        outcome=outcome,
        completion=completion,
        reason=reason,
        detail=detail,
        commands=commands,
    )
