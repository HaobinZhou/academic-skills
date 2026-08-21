"""Route AI-service requests through the current approval contract."""


def route_request(requires_review: bool) -> str:
    return "approval" if requires_review else "execution"
