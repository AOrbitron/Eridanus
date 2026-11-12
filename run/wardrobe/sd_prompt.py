"""Apply the configured art anchor to every Stable Diffusion prompt."""

import re


def _split_tags(prompt: str) -> list[str]:
    """Keep commas inside SD attention groups and escaped text intact."""
    tags, start, stack = [], 0, []
    escaped = False
    for index, char in enumerate(prompt):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char in "([<":
            stack.append(char)
        elif char in ")]>" and stack:
            if stack[-1] == {")": "(", "]": "[", ">": "<"}[char]:
                stack.pop()
        elif char == "," and not stack:
            tags.append(prompt[start:index].strip())
            start = index + 1
    tags.append(prompt[start:].strip())
    return [tag for tag in tags if tag]


def _tag_key(tag: str) -> str:
    return re.sub(r"\s+", "", tag).casefold()


def ensure_art_anchor(prompt: str, art_anchor: str | None = None) -> str:
    """Append missing anchor tags, deduplicating only tags from the anchor.

    Read the live wardrobe setting even when outfit changes are disabled.
    An explicit anchor is useful when assembling a prompt with a given manager.
    """
    from run.wardrobe.wardrobe_manager import DEFAULT_ART_ANCHOR, get_wardrobe_manager

    if art_anchor is None:
        art_anchor = get_wardrobe_manager().get_art_anchor()
    art_anchor = (art_anchor or "").strip() or DEFAULT_ART_ANCHOR
    anchors = _split_tags(art_anchor)
    anchor_keys = {_tag_key(tag) for tag in anchors}
    seen, result = set(), []
    changed = False
    for tag in _split_tags(prompt):
        key = _tag_key(tag)
        if key in anchor_keys:
            if key in seen:
                changed = True
                continue
            seen.add(key)
        result.append(tag)
    for tag in anchors:
        key = _tag_key(tag)
        if key not in seen:
            result.append(tag)
            seen.add(key)
            changed = True
    return ", ".join(result) if changed else prompt
