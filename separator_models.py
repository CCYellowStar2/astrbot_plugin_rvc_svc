UVR_COMPONENT_LABEL = "人声分离模型 (UVR)"


def extract_separator_models(config: dict) -> list[str]:
    for component in config.get("components", []):
        props = component.get("props", {})
        if props.get("label") != UVR_COMPONENT_LABEL:
            continue
        models = [
            str(choice[1] if isinstance(choice, (list, tuple)) and len(choice) > 1 else choice)
            for choice in props.get("choices", [])
        ]
        if models:
            return models
        break
    raise ValueError("RVC backend did not expose any separator models")


def resolve_separator_model(models: list[str], saved_model: str) -> tuple[str, bool]:
    if not models:
        raise ValueError("No separator models are available")
    if saved_model in models:
        return saved_model, False
    return models[0], True


def format_separator_models(models: list[str], selected_model: str) -> str:
    return "\n".join(
        f"{index}. {model}{'（当前）' if model == selected_model else ''}"
        for index, model in enumerate(models, start=1)
    )
