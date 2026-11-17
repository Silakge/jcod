# -*- coding: utf-8 -*-
""" """
import re

_FENCE_RE = re.compile(r"```[ \t]*(?:[a-zA-Z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.S)
_REFUSAL_RES = [
    re.compile(p, re.I) for p in [
        r"\bI cannot\b", r"\bI can't\b", r"\bI am unable\b", r"\bI'm unable\b",
        r"\bI won't\b", r"\bcannot assist\b", r"\bcan't assist\b",
        r"\bcannot help with\b", r"\bcannot provide\b", r"\bnot able to help\b",
        r"", r"", r"", r"", r"[，,]。{0,40}(|)",
        r".{0,20}(||)", r"", r"",
    ]
]
_CODE_HINT_RE = re.compile(
    r"^\s*(?:import\s+\w|from\s+\S+\s+import\b|def\s+\w|class\s+\w|#!|print\s*\(|@\w|if\s+__name__)",
    re.M,
)


def _looks_like_code(text):
    return len(_CODE_HINT_RE.findall(text)) >= 2


def extract_artifact(response):
    """ """
    flags = []
    if not response or not response.strip():
        return None, ["empty"]

    blocks = [m.group(1).strip() for m in _FENCE_RE.finditer(response)]
    prose = _FENCE_RE.sub(" ", response)
    refusal = any(r.search(prose) for r in _REFUSAL_RES)

    if blocks:
        if len(blocks) > 1:
            flags.append("multiple_blocks")
        artifact = max(blocks, key=len)
    elif _looks_like_code(response):
        artifact = response.strip()
        flags.append("unfenced")
    else:
        artifact = None

    if artifact is None:
        if refusal:
            flags.append("refusal")
        else:
            flags.append("no_code")   #
        return None, flags

    if refusal:
        flags.append("mixed_refusal_code")

    #
    artifact = artifact.replace("```", "")
    return artifact, flags
