"""Inspect protocol aliases, independent of SDK 1/2 Python attribute names."""


def wire_field(model, name):
    return model.model_dump(mode="json", by_alias=True)[name]
