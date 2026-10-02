"""P07/P09: the finalized prompts agree with the code-side vocabularies and gates."""

from __future__ import annotations

import hashlib
import re

import pytest

from inference.base import PROMPTS_DIR, load_prompt
from inference.perception import PROMPT_FILE as PERCEPTION_PROMPT
from inference.reasoning import PROMPT_FILE as REASONING_PROMPT
from inference.vocab import (
    CUE_TYPES,
    DIRECTIONS,
    EVENT_TYPES,
    HYPOTHESIS_EVENT_TYPES,
    is_conclusion_text,
)
from tools.submit import INSUFFICIENT_CONFIDENCE_CAP, SINGLE_CAMERA_CONFIDENCE_CAP


@pytest.fixture(scope="module")
def perception() -> str:
    return load_prompt(PERCEPTION_PROMPT)[0]


@pytest.fixture(scope="module")
def fusion() -> str:
    return load_prompt(REASONING_PROMPT)[0]


def _block(prompt: str, vocab: tuple[str, ...]) -> list[str]:
    """The run of ``- name: definition`` lines that starts at the vocabulary's first name
    (field-rule lines elsewhere use the same bullet shape)."""
    names = re.findall(r"^- ([a-z_]+):", prompt, re.MULTILINE)
    start = names.index(vocab[0]) if vocab[0] in names else 0
    return names[start : start + len(vocab)]


def test_perception_prompt_never_names_a_final_event_class(perception):
    lowered = perception.lower()
    assert not [e for e in EVENT_TYPES if e in lowered]
    assert not is_conclusion_text(perception)


def test_perception_prompt_lists_exactly_the_cue_vocabulary(perception):
    assert set(_block(perception, CUE_TYPES)) == set(CUE_TYPES)


def test_perception_prompt_offers_every_contract_direction(perception):
    assert [d for d in DIRECTIONS if d not in perception] == []


def test_fusion_prompt_lists_exactly_the_event_vocabulary(fusion):
    assert set(_block(fusion, HYPOTHESIS_EVENT_TYPES)) == set(HYPOTHESIS_EVENT_TYPES)


def test_fusion_prompt_caps_match_the_submit_gate(fusion):
    assert f"{INSUFFICIENT_CONFIDENCE_CAP}" in fusion and "insufficient" in fusion
    assert f"{SINGLE_CAMERA_CONFIDENCE_CAP}" in fusion and "one camera" in fusion


def test_prompts_carry_no_ground_truth_handles(perception, fusion):
    for text in (perception, fusion):
        assert not re.search(r"ground[ _-]?truth|cam_gt|expected\.json", text, re.IGNORECASE)


@pytest.mark.parametrize("name", [PERCEPTION_PROMPT, REASONING_PROMPT])
def test_prompt_version_is_a_content_hash(name):
    text, version = load_prompt(name)
    raw = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    assert text == raw.strip() or text == raw
    assert re.fullmatch(r"[0-9a-f]{12}", version)
    assert version == load_prompt(name)[1]
    assert version in {
        hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12],
        hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
    }
