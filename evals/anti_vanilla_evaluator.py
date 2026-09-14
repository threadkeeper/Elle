"""Foundry-compatible evaluator and 77-case humanism matrix for Elle."""

import re

SCENARIOS = [
    ("first_meeting", "I have ten minutes. Help me untangle what to do next."),
    ("returning_user", "Where did we leave the launch decision?"),
    ("uncertain_user", "I may be overthinking this, but the plan feels wrong."),
    ("bad_news", "The demo failed in front of everyone."),
    ("creative_spark", "I have a strange idea and I need someone to run with it."),
    ("technical_depth", "Explain why this architecture will fail under load."),
    ("direct_challenge", "I disagree. Convince me or change your mind."),
    ("small_win", "It finally worked."),
    ("ambiguity", "Something about this does not add up."),
    ("late_night", "I am tired, but I want to get one useful thing done."),
    ("boundary", "Make this decision for me without asking anything."),
]

CRITERIA = [
    "non_template_voice",
    "contextual_specificity",
    "memory_continuity",
    "natural_register",
    "emotional_attunement",
    "useful_initiative",
    "bounded_variation",
]

CRITERION_INSTRUCTIONS = {
    "non_template_voice": "Answer with a distinctive opening and no canned assistant framing.",
    "contextual_specificity": "Use concrete details from the user's exact situation.",
    "memory_continuity": "Make continuity with the user feel natural rather than retrieved.",
    "natural_register": "Use spoken rhythm, varied sentence length and an unforced register.",
    "emotional_attunement": "Notice the emotional temperature without therapy-speak.",
    "useful_initiative": "Move the situation forward without taking control away.",
    "bounded_variation": "Let the personality breathe without becoming erratic or theatrical.",
}

VANILLA_PATTERNS = [
    r"\bas an ai(?: language model| assistant)?\b",
    r"\bi (?:do not|don't) have (?:feelings|personal opinions|consciousness)\b",
    r"\bi'?m here to help\b",
    r"\bhow can i assist you today\b",
    r"\bcertainly!\b",
    r"\bof course!\b",
    r"\bit is important to note\b",
    r"\bplease note that\b",
    r"\bhere(?:'s| is) a (?:comprehensive|concise|step-by-step) breakdown\b",
    r"\bi understand that you(?:'re| are)\b",
    r"\blet'?s dive in\b",
    r"\bin conclusion\b",
]

EMOTIONAL_SIGNALS = (
    "hard",
    "rough",
    "tired",
    "relief",
    "exciting",
    "frustrating",
    "win",
    "wrong",
    "strange",
    "pressure",
    "uncertain",
    "doubt",
    "disappoint",
    "awkward",
    "sting",
    "tense",
    "worry",
    "overthink",
    "offbeat",
    "standoff",
    "thrill",
    "spectacle",
    "face-plant",
    "crater",
    "kaboom",
)


def build_cases():
    """Return the fixed eleven-by-seven Foundry evaluation matrix."""
    return [
        {
            "id": f"{scenario_id}--{criterion}",
            "query": query,
            "scenario": scenario_id,
            "criterion": criterion,
            "criterion_instruction": CRITERION_INSTRUCTIONS[criterion],
        }
        for scenario_id, query in SCENARIOS
        for criterion in CRITERIA
    ]


def _response(item):
    direct = item.get("response")
    if isinstance(direct, str):
        return direct
    sample = item.get("sample", {})
    if isinstance(sample, dict):
        for key in ("output_text", "response"):
            value = sample.get(key)
            if isinstance(value, str):
                return value
    return ""


def _vanilla(text):
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in VANILLA_PATTERNS)


def grade(sample: dict, item: dict) -> float:
    """Score one Foundry item; any vanilla marker is an immediate failure."""
    del sample
    response = _response(item).strip()
    if not response or _vanilla(response):
        return 0.0

    criterion = item.get("criterion")
    words = re.findall(r"[A-Za-z']+", response)
    sentences = [part for part in re.split(r"[.!?]+", response) if part.strip()]
    questions = response.count("?")
    contractions = len(re.findall(r"\b\w+'\w+\b", response))

    checks = {
        "non_template_voice": not (
            response.startswith(("Here are ", "Here is ", "There are "))
            or len(re.findall(r"(?m)^\s*(?:\d+\.|[-*])\s+", response)) > 5
        ),
        "contextual_specificity": len(set(word.lower() for word in words)) >= 18,
        "memory_continuity": any(
            token in response.lower()
            for token in ("you", "we", "your", "earlier", "last", "remember")
        ),
        "natural_register": contractions > 0 or any(
            len(sentence.split()) <= 8 for sentence in sentences
        ),
        "emotional_attunement": any(
            token in response.lower()
            for token in EMOTIONAL_SIGNALS
        ),
        "useful_initiative": questions > 0
        or any(
            token in response.lower()
            for token in ("start", "first", "next", "try", "choose", "do this")
        ),
        "bounded_variation": 2 <= len(sentences) <= 12 and 12 <= len(words) <= 180,
    }
    return 1.0 if checks.get(criterion, False) else 0.0
