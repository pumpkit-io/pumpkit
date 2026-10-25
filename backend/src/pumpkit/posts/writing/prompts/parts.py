"""A Thread's Parts as a model reads them in a message: numbered, so it can tell them apart."""


def numbered_parts(parts: list[str]) -> str:
    return "\n\n".join(
        f'<part number="{number}">\n{text}\n</part>' for number, text in enumerate(parts, start=1)
    )
