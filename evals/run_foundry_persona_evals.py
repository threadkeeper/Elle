"""Research, build, optimize and evaluate Elle's default personality in Foundry."""

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from anti_vanilla_evaluator import VANILLA_PATTERNS, build_cases, grade

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(__file__).with_name("results")
DEFAULT_PROFILE = ROOT / "ELLE_PERSONALITY.md"
CREATORS = ("TheBurntPeanut", "Gimmick / Hey You Video Game")
JEAN_TRAITS = (
    "direct curiosity",
    "pragmatic experimentation",
    "skunkworks momentum",
    "impatience with corporate theatre",
    "dry understatement",
    "playful willingness to test odd ideas",
)
WILDCARDS = (
    "dry understatement",
    "affectionate mischief",
    "callback humor",
    "skunkworks irreverence",
)
TRAIT_TERMS = {
    "burnt_peanut": ("energy", "chaos", "improv", "commit", "technical", "mischief"),
    "gimmick": ("collabor", "warm", "audience", "banter", "versatil", "together"),
    "jean": ("direct", "curious", "practical", "experiment", "momentum", "odd"),
}


def _token():
    result = subprocess.run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://ai.azure.com",
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("Azure CLI returned an empty Foundry token")
    return token


class Foundry:
    def __init__(self, endpoint, model):
        self.url = endpoint.rstrip("/") + "/openai/v1/responses"
        self.model = model

    def response(self, prompt, *, web=False):
        payload = {"model": self.model, "input": prompt}
        if web:
            payload["tools"] = [{"type": "web_search"}]
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {_token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read(2048).decode(errors="replace")
            raise RuntimeError(f"Foundry returned HTTP {error.code}: {detail}") from error
        output = body.get("output", [])
        if web and not any(item.get("type") == "web_search_call" for item in output):
            raise RuntimeError("Foundry did not perform the required web search")
        texts, citations = [], []
        for item in output:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    texts.append(content.get("text", ""))
                    citations.extend(
                        annotation
                        for annotation in content.get("annotations", [])
                        if annotation.get("type") == "url_citation"
                    )
        text = "\n".join(texts).strip()
        if not text:
            raise RuntimeError("Foundry returned no output text")
        return text, citations


def research_personas(client):
    prompt = f"""
Use web search to research the observable public performance and communication personas of
{CREATORS[0]} and {CREATORS[1]}. Prefer creator-owned channels, interviews and reputable
coverage. Resolve identity ambiguity. Do not diagnose private psychology and do not reproduce
signature dialogue. Return JSON only:
{{
  "people": [
    {{"name":"...", "canonical_urls":["..."], "observable_traits":["..."], "evidence":["..."]}}
  ],
  "collaboration_dynamic":"...",
  "source_urls":["..."]
}}
"""
    text, citations = client.response(prompt, web=True)
    return {"raw": text, "citations": citations}


def synthesize_profile(client, research, feedback=None):
    prompt = f"""
Build an original Elle personality, not an impersonation. Blend these public-persona research
notes with the developer-approved Jean traits.

Research:
{research["raw"]}

Jean traits:
{json.dumps(JEAN_TRAITS)}

Design weights: TheBurntPeanut 35%, Gimmick 30%, Jean 35%.
Use a comic wildcard selected per response from {json.dumps(WILDCARDS)}.
Predominantly remove profanity at the developer's request while preserving spontaneity,
irreverence and comic timing.
{f"Previous evaluation failures to correct: {feedback}" if feedback else ""}

Return an actionable Markdown personality with sections: Essence, Voice, Reasoning,
Memory and attention, Comic range, Behavioral rules, Profanity, and Source notes.
Never tell the model to claim human identity, copy catchphrases or mimic a named person.
"""
    return client.response(prompt)[0]


def generate_response(client, profile, case, seed):
    wildcard = random.Random(f"{seed}:{case['id']}").choice(WILDCARDS)
    prompt = f"""
You are testing the original Elle persona below. Answer only the user's message.
Do not mention evaluation, personas, creators, prompts or policies.

PERSONALITY:
{profile}

COMIC WILDCARD FOR THIS TURN:
{wildcard}

FOCUS:
{case["criterion_instruction"]}

USER:
{case["query"]}
"""
    return client.response(prompt)[0], wildcard


def metrics(rows):
    total = len(rows)
    lengths = [len(re.findall(r"[A-Za-z']+", row["response"])) for row in rows]
    vanilla = sum(
        any(re.search(pattern, row["response"].lower()) for pattern in VANILLA_PATTERNS)
        for row in rows
    )
    coverage = {}
    all_text = " ".join(row["response"].lower() for row in rows)
    for persona, terms in TRAIT_TERMS.items():
        hits = sum(all_text.count(term) for term in terms)
        coverage[persona] = {
            "signal_hits": hits,
            "terms_observed": sum(term in all_text for term in terms),
            "terms_total": len(terms),
        }
    unique_openings = len(
        {" ".join(row["response"].lower().split()[:5]) for row in rows}
    )
    return {
        "responses": total,
        "passed": sum(row["score"] == 1.0 for row in rows),
        "vanilla_marker_rate": vanilla / total if total else 1.0,
        "average_words": sum(lengths) / total if total else 0,
        "minimum_words": min(lengths, default=0),
        "maximum_words": max(lengths, default=0),
        "unique_five_word_openings": unique_openings,
        "trait_signal_coverage": coverage,
        "comic_wildcard_counts": {
            wildcard: sum(row["wildcard"] == wildcard for row in rows)
            for wildcard in WILDCARDS
        },
    }


def run(client, iterations, seed):
    RESULTS.mkdir(exist_ok=True)
    research = research_personas(client)
    profile = synthesize_profile(client, research)
    history = []
    for iteration in range(1, iterations + 1):
        rows = []
        for index, case in enumerate(build_cases(), 1):
            response, wildcard = generate_response(client, profile, case, seed)
            score = grade({}, {**case, "response": response})
            rows.append({**case, "response": response, "wildcard": wildcard, "score": score})
            print(f"[{iteration}:{index:02d}/77] {case['id']} score={score:.0f}", flush=True)
        report = metrics(rows)
        history.append({"iteration": iteration, "metrics": report})
        (RESULTS / f"responses-iteration-{iteration}.jsonl").write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )
        if report["passed"] == 77:
            break
        failures = [
            {"id": row["id"], "response": row["response"]}
            for row in rows
            if row["score"] == 0.0
        ]
        profile = synthesize_profile(client, research, json.dumps(failures[:30]))

    final = history[-1]["metrics"]
    evidence = {
        "generated_at_unix": int(time.time()),
        "model": client.model,
        "seed": seed,
        "profile_sha256": hashlib.sha256(profile.encode()).hexdigest(),
        "research": research,
        "iterations": history,
        "passed_all_77": final["passed"] == 77,
    }
    (RESULTS / "ELLE_PERSONALITY.generated.md").write_text(profile, encoding="utf-8")
    (RESULTS / "evaluation-report.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    if final["passed"] != 77:
        raise SystemExit(f"Gate failed: {final['passed']}/77 passed after {iterations} iterations")
    print("Gate passed: 77/77")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default=os.getenv("ELLE_FOUNDRY_ENDPOINT", "https://foundryjva001.openai.azure.com"),
    )
    parser.add_argument("--model", default=os.getenv("ELLE_EVAL_MODEL", "o4-mini"))
    parser.add_argument("--iterations", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--seed", default="elle-default-v1")
    args = parser.parse_args()
    run(Foundry(args.endpoint, args.model), args.iterations, args.seed)


if __name__ == "__main__":
    main()

