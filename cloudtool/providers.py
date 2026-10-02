"""Provider registry. Additional platforms implement their own adapter and UI factory."""
PROVIDERS = {}


def register(key, title, adapter):
    if key in PROVIDERS:
        raise ValueError(f"Duplicate provider: {key}")
    PROVIDERS[key] = {"title": title, "adapter": adapter}
