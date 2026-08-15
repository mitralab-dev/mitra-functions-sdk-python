from urllib.parse import quote


def encode_path_segment(value: str | int, field_name: str) -> str:
    segment = str(value)
    if not segment.strip():
        raise ValueError(f"{field_name} must not be blank")
    if segment in {".", ".."}:
        raise ValueError(f"{field_name} must not be a dot segment")
    return quote(segment, safe="")
