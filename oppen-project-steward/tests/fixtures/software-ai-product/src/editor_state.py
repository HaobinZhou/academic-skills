"""Apply the editor-state contract for generated drafts."""


def may_generate(state: str, approved: bool) -> bool:
    return state == "ready" and approved
