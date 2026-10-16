"""Landing and failure labels taken from the physics state.

Gymnasium's own terminal reward is not a reliable landing label: on the step
the hull touches the moon it assigns -100, then overwrites that value with
+100 if the lander body is asleep. Primary scoring still uses the reward
Gymnasium returned.

A successful landing additionally requires the lander body to be between the
two flag poles (``helipad_x1`` and ``helipad_x2``). Settling elsewhere is
recorded as its own outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

LANDED = "landed"
LANDED_OUTSIDE_ZONE = "landed_outside_zone"
SETTLED_ZONE_UNKNOWN = "settled_zone_unknown"
PHYSICAL_CRASH = "physical_crash"
VIEWPORT_EXIT = "viewport_exit"
TIMEOUT = "timeout"
TERMINATED_OTHER = "terminated_other"
INCOMPLETE = "incomplete"
INVALID = "invalid"

OUTCOME_LABELS: tuple[str, ...] = (
    LANDED,
    LANDED_OUTSIDE_ZONE,
    SETTLED_ZONE_UNKNOWN,
    PHYSICAL_CRASH,
    VIEWPORT_EXIT,
    TIMEOUT,
    TERMINATED_OTHER,
    INCOMPLETE,
    INVALID,
)


@dataclass(frozen=True)
class PhysicsSnapshot:
    terminated: bool
    truncated: bool
    game_over: bool
    out_of_bounds: bool
    lander_awake: bool | None
    in_landing_zone: bool | None = None
    lander_x: float | None = None
    helipad_x1: float | None = None
    helipad_x2: float | None = None


@dataclass(frozen=True)
class FlightOutcome:
    landed: bool
    crashed: bool
    viewport_exit: bool
    timed_out: bool
    label: str
    crash_cause: str | None
    in_landing_zone: bool | None


def classify_outcome(snapshot: PhysicsSnapshot) -> FlightOutcome:
    """Classify a finished step.

    ``landed`` is true only for an in-zone settlement: the episode terminated,
    the hull did not touch the surface, the craft stayed inside the viewport,
    the body is asleep, and its x position is between the flag poles.
    """
    if snapshot.terminated and snapshot.game_over:
        return FlightOutcome(
            landed=False,
            crashed=True,
            viewport_exit=snapshot.out_of_bounds,
            timed_out=False,
            label=PHYSICAL_CRASH,
            crash_cause="hull_contact",
            in_landing_zone=snapshot.in_landing_zone,
        )
    if snapshot.terminated and snapshot.out_of_bounds:
        return FlightOutcome(
            landed=False,
            crashed=False,
            viewport_exit=True,
            timed_out=False,
            label=VIEWPORT_EXIT,
            crash_cause="out_of_bounds",
            in_landing_zone=snapshot.in_landing_zone,
        )
    if snapshot.terminated and snapshot.lander_awake is False:
        if snapshot.in_landing_zone is True:
            label = LANDED
            landed = True
        elif snapshot.in_landing_zone is False:
            label = LANDED_OUTSIDE_ZONE
            landed = False
        else:
            label = SETTLED_ZONE_UNKNOWN
            landed = False
        return FlightOutcome(
            landed=landed,
            crashed=False,
            viewport_exit=False,
            timed_out=False,
            label=label,
            crash_cause=None,
            in_landing_zone=snapshot.in_landing_zone,
        )
    if snapshot.terminated:
        return FlightOutcome(
            landed=False,
            crashed=False,
            viewport_exit=False,
            timed_out=False,
            label=TERMINATED_OTHER,
            crash_cause=None,
            in_landing_zone=snapshot.in_landing_zone,
        )
    if snapshot.truncated:
        return FlightOutcome(
            landed=False,
            crashed=False,
            viewport_exit=False,
            timed_out=True,
            label=TIMEOUT,
            crash_cause=None,
            in_landing_zone=snapshot.in_landing_zone,
        )
    return FlightOutcome(
        landed=False,
        crashed=False,
        viewport_exit=False,
        timed_out=False,
        label=INCOMPLETE,
        crash_cause=None,
        in_landing_zone=snapshot.in_landing_zone,
    )
