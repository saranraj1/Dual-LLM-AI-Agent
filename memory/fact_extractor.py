"""
memory/fact_extractor.py — Automated extraction of architectural decisions,
stack constraints, and coding conventions from conversational turns.
"""

import re
from typing import List, Dict, Any, Optional
from memory.storage import get_db, normalize_workspace
from memory.long_memory import LongMemory

# Regex rules for detecting architectural facts and conventions
_FACT_PATTERNS = [
    # ADR / Decisions: "ADR-004: We decided to use...", "decision is to..."
    (
        re.compile(r"(?:(adr[-_0-9]+)\s*:\s*|we\s+decided\s+to|decision\s+is\s+to\s*)([\w\s\.\-_]+?)(?:because|\.|$)", re.IGNORECASE),
        "adr",
        "architecture",
        "decided"
    ),
    # Stack constraints: "tech stack: Python 3.11", "we use FastAPI"
    (
        re.compile(r"(?:tech\s+stack\s*:\s*|we\s+use|we\s+are\s+using|stack\s+is|framework\s+is)\s+([\w\s\.\-_/]+?)(?:\s+for|\.|$)", re.IGNORECASE),
        "stack",
        "tech_stack",
        "uses"
    ),
    # Invariant Constraints: "architecture rule: use...", "constraint: never execute...", "always use model_dump()"
    (
        re.compile(r"(?:architecture\s+rule\s*:\s*|constraint\s*:\s*|(?:always|never|must)\s+)([\w\s\.\-_/\(\)]+?)(?:\.|$)", re.IGNORECASE),
        "constraint",
        "engineering_rule",
        "enforces"
    ),
    # Coding Conventions: "convention: always...", "convention is to put..."
    (
        re.compile(r"(?:convention\s*:\s*|convention\s+is\s+to|style\s+is\s+to|standard\s+is\s+to)\s+([\w\s\.\-_/]+?)(?:\.|$)", re.IGNORECASE),
        "convention",
        "code_style",
        "follows"
    ),
]


def extract_facts_from_text(text: str) -> List[Dict[str, str]]:
    """Scan text for architectural conventions or constraints."""
    facts = []
    if not text or len(text) < 10:
        return facts

    for line in text.splitlines():
        line_clean = line.strip().lstrip("-*#").strip()
        if not line_clean:
            continue
        # Check ADR explicitly
        adr_m = re.search(r"\b(adr[-_0-9]+)\b", line_clean, re.IGNORECASE)
        adr_key = adr_m.group(1).lower() if adr_m else None

        for pattern, cat, default_subj, pred in _FACT_PATTERNS:
            m = pattern.search(line_clean)
            if m:
                groups = [g for g in m.groups() if g]
                obj_val = groups[-1].strip() if groups else line_clean
                subj = adr_key if (cat == "adr" and adr_key) else default_subj
                if len(obj_val) >= 3 and len(obj_val) < 160:
                    facts.append({
                        "category": cat,
                        "subject": subj,
                        "fact_key": subj,
                        "predicate": pred,
                        "object": obj_val,
                        "fact_value": obj_val,
                        "raw_content": line_clean
                    })
                    break
    return facts


def auto_record_turn_facts(workspace: str, content: str) -> int:
    """Extract and record any detected facts from a turn into knowledge_facts table."""
    facts = extract_facts_from_text(content)
    if not facts:
        return 0

    lm = LongMemory(workspace=workspace)
    count = 0
    for f in facts:
        try:
            lm.add_fact(
                category=f["category"],
                subject=f["subject"],
                predicate=f["predicate"],
                object_val=f["object"],
                raw_content=f["raw_content"]
            )
            count += 1
        except Exception:
            pass
    return count
