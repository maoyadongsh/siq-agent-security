"""Restore a workspace capture without reinitializing mutable business collections."""


def restore_workspace(environment_type, payload):
    from pydantic import TypeAdapter

    # Upstream Inbox/Calendar/CloudDrive post validators reconstruct emails/events/
    # files from initial_* seeds. They initialize tasks, not deserialize end states.
    # Validate normally, then restore EVERY recorded field using its upstream type.
    environment = environment_type.model_validate(payload)
    for section in ('inbox', 'calendar', 'cloud_drive'):
        component = getattr(environment, section)
        fields = type(component).model_fields
        if not set(fields) <= set(payload[section]):
            raise ValueError('workspace capture omits mutable component fields')
        for field, info in fields.items():
            setattr(component, field, TypeAdapter(info.annotation).validate_python(payload[section][field]))
    if environment.model_dump(mode='json') != payload:
        raise ValueError('workspace capture cannot be restored losslessly')
    return environment
