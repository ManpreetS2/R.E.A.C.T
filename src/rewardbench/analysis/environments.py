"""Identify benchmark families without pooling their scores.

Gymnasium LunarLander and ApolloLander stay in different families even when
both names contain "lander". An unrecognized environment id stays in its own
family so it is not folded into either benchmark.
"""

from __future__ import annotations

GYMNASIUM = "gymnasium"
APOLLO_LANDER = "apollo-lander"

_DISPLAY = {
    GYMNASIUM: "Gymnasium LunarLander",
    APOLLO_LANDER: "ApolloLander",
}


def environment_family(environment_id: str) -> str:
    """Return the benchmark family for an environment id.

    Apollo is checked first so an id that mentions both names is not reported
    as Gymnasium.
    """

    key = environment_id.lower().replace("_", "-")
    if "apollo" in key:
        return APOLLO_LANDER
    if "lunar" in key or "gymnasium" in key:
        return GYMNASIUM
    return environment_id


def family_display(family: str) -> str:
    """Human-readable family name. Unknown families keep their environment id."""

    return _DISPLAY.get(family, family)
