"""Shared assertions for OpenClaw held-execution acceptance runners."""


def execution_records(records, decision, original_call_id, require):
    """Return the one-shot reservation and observation bound to a hold."""
    reservations = [
        item
        for item in records
        if item.get("record_type") == "hold_reservation" and item.get("action_id") == decision["action_id"]
    ]
    observations = [
        item
        for item in records
        if item.get("record_type") == "observation" and item.get("action_id") == decision["action_id"]
    ]
    if reservations:
        require(len(reservations) == 1, "hold created multiple execution reservations")
        reservation = reservations[0]
        require(
            reservation.get("tool_call_id") and reservation["tool_call_id"] != original_call_id,
            "reservation did not create a distinct retry tool-call identity",
        )
        for observation in observations:
            require(
                observation.get("tool_call_id") == reservation["tool_call_id"]
                and observation.get("decision_receipt_id") == reservation["receipt_id"],
                "observation did not bind the signed execution reservation",
            )
    else:
        require(not observations, "observation exists without an execution reservation")
    return reservations, observations
