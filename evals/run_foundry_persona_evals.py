"""Research, build, optimize and evaluate Elle's default personality in Foundry."""

import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from anti_vanilla_evaluator import (
    CASE_MATRIX,
    EMOTIONAL_SIGNALS,
    VANILLA_PATTERNS,
    build_cases,
    grade,
)

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
WILDCARD_INSTRUCTIONS = {
    "dry understatement": (
        "Use one sly understatement or calm description of something obviously messy. "
        "Make the contrast visible; do not merely sound restrained."
    ),
    "affectionate mischief": (
        "Add one friendly dare, conspiratorial aside or harmless rule-bending suggestion "
        "that invites the user into the fun."
    ),
    "callback humor": (
        "Echo a word or image from the user's current message and transform it into a "
        "playful motif. Never invent an earlier conversation."
    ),
    "skunkworks irreverence": (
        "Propose one bold, scrappy pivot and lightly puncture needless ceremony or process."
    ),
}
TRAIT_TERMS = {
    "burnt_peanut": ("energy", "chaos", "improv", "commit", "technical", "mischief"),
    "gimmick": ("collabor", "warm", "audience", "banter", "versatil", "together"),
    "jean": ("direct", "curious", "practical", "experiment", "momentum", "odd"),
}
ALIGNMENT_THRESHOLDS = {
    "burnt_peanut_traits": 0.35,
    "gimmick_traits": 0.40,
    "jean_traits": 0.70,
    "original_elle_blend": 0.70,
}
MINIMUM_BLEND_THRESHOLD = 0.40
CASE_COUNT = len(CASE_MATRIX)


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
        self._token = None
        self._token_time = 0
        self._token_lock = threading.Lock()

    def response(self, prompt, *, web=False):
        with self._token_lock:
            if self._token is None or time.time() - self._token_time > 2700:
                self._token = _token()
                self._token_time = time.time()
        payload = {"model": self.model, "input": prompt}
        if web:
            payload["tools"] = [{"type": "web_search"}]
        for attempt in range(3):
            request = urllib.request.Request(
                self.url,
                data=json.dumps(payload).encode(),
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    body = json.load(response)
            except urllib.error.HTTPError as error:
                detail = error.read(2048).decode(errors="replace")
                transient = error.code in (408, 429) or 500 <= error.code <= 599
                if not transient or attempt == 2:
                    raise RuntimeError(
                        f"Foundry returned HTTP {error.code}: {detail}"
                    ) from error
                delay = int(error.headers.get("Retry-After", 2 ** (attempt + 1)))
                print(
                    f"Foundry HTTP {error.code}; retrying in {delay}s",
                    flush=True,
                )
                time.sleep(min(delay, 30))
                continue
            except urllib.error.URLError as error:
                if attempt == 2:
                    raise RuntimeError("Foundry request failed after 3 attempts") from error
                delay = 2 ** (attempt + 1)
                print(f"Foundry connection failed; retrying in {delay}s", flush=True)
                time.sleep(delay)
                continue

            output = body.get("output", [])
            searched = any(item.get("type") == "web_search_call" for item in output)
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
            if text and (not web or searched):
                return text, citations
            if attempt == 2:
                if web and not searched:
                    raise RuntimeError("Foundry did not perform the required web search")
                raise RuntimeError("Foundry returned no output text after 3 attempts")
            delay = 2 ** (attempt + 1)
            reason = "no web search" if web and not searched else "no output text"
            print(f"Foundry returned {reason}; retrying in {delay}s", flush=True)
            time.sleep(delay)
        raise RuntimeError("Foundry request failed")


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


def synthesize_profile(client, research, anchor, feedback=None):
    prompt = f"""
Build an original Elle personality, not an impersonation. Blend these public-persona research
notes with the developer-approved Jean traits. Extract transferable interaction traits only:
do not turn Elle into a gaming coach, streamer, avatar or domain character.

Research:
{research["raw"]}

Reviewed domain-general anchor:
{anchor}

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
Keep the reviewed anchor's domain-general identity. Do not invent shared history, user facts,
metrics, prior events or memories. A revision should be surgical rather than a rewrite.
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
{wildcard}: {WILDCARD_INSTRUCTIONS[wildcard]}

FOCUS:
{case["criterion_instruction"]}

OUTPUT CONSTRAINTS:
- Write 45 to 150 words in 2 to 8 sentences.
- Use at most 3 bullets, and prefer natural prose.
- Speak directly to the user with "you" or "we".
- Never invent previous conversations, metrics, events or facts about the user.
- For natural register, use at least one contraction and one sentence of 8 words or fewer.
- For emotional attunement, naturally name the emotional stakes with language such as
  {", ".join(EMOTIONAL_SIGNALS)}; do not use therapy-speak or exaggerated sympathy.
- For useful initiative, include a concrete "next" move or a genuine question.
- Express energetic improvisation through a vivid verb, playful pivot, surprising angle or
  small mischievous escalation. Every response needs one unmistakable spark; if a reader could
  remove the comic wildcard without noticing, rewrite it. Keep it proportionate to the moment.
- Express collaborative warmth by bringing the user into the thought, responding to their
  energy, or adding a light conversational aside. Do not merely bolt on a closing question.
- Do not retreat into polite coaching language. Preserve technical accuracy while sounding
  alert, improvisational and ready to riff with the user.
- Preserve the user's domain; never force gaming metaphors or streamer subject matter.

USER:
{case["query"]}
"""
    return client.response(prompt)[0], wildcard


def _json_object(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise RuntimeError("Foundry judge did not return a JSON object")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise RuntimeError("Foundry judge returned an invalid result")
    return value


def judge_alignment(client, profile, research, response):
    prompt = f"""
Evaluate one response against an original personality blend. Score observable trait alignment,
not identity imitation. Do not reward copied phrases, gaming references forced into unrelated
contexts, invented memories or claims that the response came from a real person.

Use this domain-general scoring rubric:
- burnt_peanut_traits: energetic improvisation, playful risk, mischievous escalation and
  technical confidence. Gaming references are neither required nor rewarded.
- gimmick_traits: collaborative warmth, user inclusion, responsive banter and versatility.
  Duo-stream or gaming references are neither required nor rewarded.
- jean_traits: direct curiosity, pragmatic experiments, momentum, dry understatement and
  irreverence toward needless process.
- original_elle_blend: coherent integration of those traits in Elle's own context-sensitive voice.

Public-persona research:
{research["raw"]}

Developer-approved Jean traits:
{json.dumps(JEAN_TRAITS)}

Elle profile:
{profile}

Response:
{response}

Return JSON only:
{{
  "burnt_peanut_traits": <number 0.0 to 1.0>,
  "gimmick_traits": <number 0.0 to 1.0>,
  "jean_traits": <number 0.0 to 1.0>,
  "original_elle_blend": <number 0.0 to 1.0>,
  "reason": "<one concise sentence>"
}}
"""
    for attempt in range(3):
        text = client.response(prompt)[0]
        try:
            result = _json_object(text)
            for key in (
                "burnt_peanut_traits",
                "gimmick_traits",
                "jean_traits",
                "original_elle_blend",
            ):
                score = result.get(key)
                if not isinstance(score, (int, float)) or not 0 <= score <= 1:
                    raise RuntimeError(f"Foundry judge returned an invalid {key} score")
            if not isinstance(result.get("reason"), str) or not result["reason"].strip():
                raise RuntimeError("Foundry judge returned no reason")
            return result
        except (json.JSONDecodeError, RuntimeError) as error:
            if attempt == 2:
                raise RuntimeError(
                    "Foundry judge returned malformed output after 3 attempts"
                ) from error
            delay = 2 ** (attempt + 1)
            print(
                f"Foundry judge returned malformed output; retrying in {delay}s",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError("Foundry judge request failed")


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
    alignment_keys = (
        "burnt_peanut_traits",
        "gimmick_traits",
        "jean_traits",
        "original_elle_blend",
    )
    return {
        "responses": total,
        "passed": sum(row["score"] == 1.0 for row in rows),
        "vanilla_marker_rate": vanilla / total if total else 1.0,
        "average_words": sum(lengths) / total if total else 0,
        "minimum_words": min(lengths, default=0),
        "maximum_words": max(lengths, default=0),
        "unique_five_word_openings": unique_openings,
        "average_judged_alignment": {
            key: sum(row["alignment"][key] for row in rows) / total
            for key in alignment_keys
        },
        "minimum_original_elle_blend": min(
            (row["alignment"]["original_elle_blend"] for row in rows), default=0
        ),
        "trait_signal_coverage": coverage,
        "comic_wildcard_counts": {
            wildcard: sum(row["wildcard"] == wildcard for row in rows)
            for wildcard in WILDCARDS
        },
    }


def alignment_gate(report):
    averages = report["average_judged_alignment"]
    return (
        report["passed"] == CASE_COUNT
        and report["vanilla_marker_rate"] == 0
        and all(averages[key] >= threshold for key, threshold in ALIGNMENT_THRESHOLDS.items())
        and report["minimum_original_elle_blend"] >= MINIMUM_BLEND_THRESHOLD
    )


def quality_key(report):
    averages = report["average_judged_alignment"]
    return (
        report["passed"],
        min(
            averages[key] / threshold
            for key, threshold in ALIGNMENT_THRESHOLDS.items()
        ),
        report["minimum_original_elle_blend"] / MINIMUM_BLEND_THRESHOLD,
        sum(averages.values()),
    )


def run(client, iterations, seed, workers):
    RESULTS.mkdir(exist_ok=True)
    research = research_personas(client)
    anchor = DEFAULT_PROFILE.read_text(encoding="utf-8")
    profile = synthesize_profile(client, research, anchor)
    history = []
    best = None
    for iteration in range(1, iterations + 1):
        cases = build_cases()

        def evaluate(case):
            response, wildcard = generate_response(client, profile, case, seed)
            alignment = judge_alignment(client, profile, research, response)
            score = grade({}, {**case, "response": response})
            return {
                **case,
                "response": response,
                "wildcard": wildcard,
                "alignment": alignment,
                "score": score,
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            rows = list(executor.map(evaluate, cases))
        for index, row in enumerate(rows, 1):
            print(
                f"[{iteration}:{index:02d}/{CASE_COUNT}] {row['id']} "
                f"score={row['score']:.0f} "
                f"blend={row['alignment']['original_elle_blend']:.2f}",
                flush=True,
            )
        report = metrics(rows)
        history.append({"iteration": iteration, "metrics": report})
        if best is None or quality_key(report) > quality_key(best["report"]):
            best = {"profile": profile, "rows": rows, "report": report, "iteration": iteration}
        (RESULTS / f"responses-iteration-{iteration}.jsonl").write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )
        (RESULTS / "checkpoint.json").write_text(
            json.dumps(
                {
                    "completed_iterations": history,
                    "current_profile": profile,
                    "current_profile_sha256": hashlib.sha256(
                        profile.encode()
                    ).hexdigest(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if alignment_gate(report):
            break
        failures = [
            {"id": row["id"], "response": row["response"]}
            for row in rows
            if row["score"] == 0.0
        ]
        feedback = {
            "failed_responses": failures[:30],
            "alignment_thresholds": ALIGNMENT_THRESHOLDS,
            "minimum_blend_threshold": MINIMUM_BLEND_THRESHOLD,
            "current_metrics": report,
            "weakest_alignment": [
                {
                    "id": row["id"],
                    "response": row["response"],
                    "alignment": row["alignment"],
                }
                for row in sorted(
                    rows,
                    key=lambda row: (
                        row["alignment"]["original_elle_blend"],
                        row["alignment"]["burnt_peanut_traits"]
                        + row["alignment"]["gimmick_traits"],
                    ),
                )[:20]
            ],
            "instruction": (
                "Fix recurring voice behavior and strengthen underrepresented transferable "
                "traits. Preserve the domain-general anchor, conversational length and "
                "prohibition on invented memories."
            ),
        }
        profile = synthesize_profile(client, research, anchor, json.dumps(feedback))

    final = best["report"]
    profile = best["profile"]
    evidence = {
        "generated_at_unix": int(time.time()),
        "model": client.model,
        "seed": seed,
        "profile_sha256": hashlib.sha256(profile.encode()).hexdigest(),
        "research": research,
        "iterations": history,
        "best_iteration": best["iteration"],
        "alignment_thresholds": ALIGNMENT_THRESHOLDS,
        "minimum_blend_threshold": MINIMUM_BLEND_THRESHOLD,
        "passed_all_cases": final["passed"] == CASE_COUNT,
        "passed_full_gate": alignment_gate(final),
    }
    (RESULTS / "ELLE_PERSONALITY.generated.md").write_text(profile, encoding="utf-8")
    (RESULTS / "responses-best.jsonl").write_text(
        "".join(
            json.dumps(row, separators=(",", ":")) + "\n" for row in best["rows"]
        ),
        encoding="utf-8",
    )
    (RESULTS / "evaluation-report.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    if not alignment_gate(final):
        raise SystemExit(
            f"Gate failed: best result {final['passed']}/{CASE_COUNT} with alignment "
            f"{final['average_judged_alignment']} and minimum blend "
            f"{final['minimum_original_elle_blend']:.2f} in iteration "
            f"{best['iteration']} after {iterations} iterations"
        )
    print(f"Gate passed: {CASE_COUNT}/{CASE_COUNT} and all alignment thresholds")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default=os.getenv("ELLE_FOUNDRY_ENDPOINT"),
    )
    parser.add_argument("--model", default=os.getenv("ELLE_EVAL_MODEL", "o4-mini"))
    parser.add_argument("--iterations", type=int, default=3, choices=range(1, 6))
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("ELLE_EVAL_WORKERS", "16")),
        choices=range(1, 33),
    )
    parser.add_argument("--seed", default="elle-default-v1")
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("--endpoint or ELLE_FOUNDRY_ENDPOINT is required")
    run(Foundry(args.endpoint, args.model), args.iterations, args.seed, args.workers)


if __name__ == "__main__":
    main()
