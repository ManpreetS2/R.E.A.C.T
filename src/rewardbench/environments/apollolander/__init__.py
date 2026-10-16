"""Deterministic ApolloLander environment, kept separate from Gymnasium."""

from rewardbench.environments.apollolander.adapter import ENVIRONMENT_ID, ApolloLanderAdapter
from rewardbench.environments.apollolander.flight_record import (
    ENVIRONMENT_VERSION,
    FLIGHT_RECORD_SCHEMA,
    ORIGIN_DETERMINISTIC_MOCK,
    ORIGIN_HAND_SPECIFIED,
    ORIGIN_MODEL_GENERATED,
    load_flight_record,
    trace_hash,
)
from rewardbench.environments.apollolander.schema import (
    SCHEMA_ID,
    constant_controller,
    controller_schema_document,
    demonstration_guidance_controller,
    random_controller,
    validate_controller,
)
from rewardbench.environments.apollolander.starts import (
    START_SCHEDULE_VERSION,
    assert_schedules_disjoint,
    derive_start,
    development_start_catalog,
    held_out_start_catalog,
    schedule_document,
    standard_start,
)

__all__ = [
    "ENVIRONMENT_ID",
    "ENVIRONMENT_VERSION",
    "FLIGHT_RECORD_SCHEMA",
    "ORIGIN_DETERMINISTIC_MOCK",
    "ORIGIN_HAND_SPECIFIED",
    "ORIGIN_MODEL_GENERATED",
    "SCHEMA_ID",
    "START_SCHEDULE_VERSION",
    "ApolloLanderAdapter",
    "assert_schedules_disjoint",
    "constant_controller",
    "controller_schema_document",
    "demonstration_guidance_controller",
    "derive_start",
    "development_start_catalog",
    "held_out_start_catalog",
    "load_flight_record",
    "random_controller",
    "schedule_document",
    "standard_start",
    "trace_hash",
    "validate_controller",
]
