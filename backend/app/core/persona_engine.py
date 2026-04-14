"""Persona selection and prompt guidance for comment generation."""

from __future__ import annotations

import random
from typing import Any

from app.core.memory_store import MemoryStore


class PersonaEngine:
    """Build persona guidance for content generation."""

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        rng: random.Random | None = None,
    ) -> None:
        """Initialize persona registry and optional persistence helpers."""

        self.memory_store = memory_store or MemoryStore()
        self._rng = rng or random.Random()
        self._personas = self._build_personas()

    def list_personas(self) -> list[dict[str, Any]]:
        """Return all available personas."""

        return [dict(persona) for persona in self._personas]

    def select_persona(self, persona_name: str | None = None) -> dict[str, Any]:
        """Select a persona by name or choose one randomly for the current run."""

        if persona_name:
            matched_persona = self._find_persona(persona_name)
            if matched_persona is not None:
                self.memory_store.put("last_persona_id", matched_persona["id"])
                return dict(matched_persona)

        last_persona_id = self.memory_store.get("last_persona_id")
        candidates = self._personas
        if isinstance(last_persona_id, str) and len(candidates) > 1:
            filtered_candidates = [
                persona
                for persona in candidates
                if persona["id"] != last_persona_id
            ]
            if filtered_candidates:
                candidates = filtered_candidates

        selected_persona = dict(self._rng.choice(candidates))
        self.memory_store.put("last_persona_id", selected_persona["id"])
        return selected_persona

    def build_prompt(self, persona_name: str, campaign_goal: str) -> str:
        """Build persona prompt guidance."""

        persona = self._find_persona(persona_name) or self.select_persona()
        vocabulary = ", ".join(persona["vocabulary"])
        preferred_styles = ", ".join(persona["preferred_styles"])

        return (
            f"Persona: {persona['name']} ({persona['archetype']}). "
            f"Tone: {persona['tone']}. "
            f"Phrasing: {persona['phrasing']}. "
            f"Signature: {persona['signature']}. "
            f"Preferred styles: {preferred_styles}. "
            f"Use vocabulary such as {vocabulary}. "
            f"Keep the comment aligned with this goal: {campaign_goal}."
        )

    def _find_persona(self, persona_name: str) -> dict[str, Any] | None:
        """Find a persona by id or display name."""

        normalized_name = persona_name.strip().lower()
        if not normalized_name:
            return None

        for persona in self._personas:
            if persona["id"] == normalized_name or persona["name"].lower() == normalized_name:
                return persona
        return None

    def _build_personas(self) -> list[dict[str, Any]]:
        """Create the full persona registry."""

        archetypes = {
            "analytical expert": {
                "tone": "measured, exact, and evidence-led",
                "phrasing": "leans on frameworks, signals, and operating tradeoffs",
                "vocabulary": ["operating model", "signal", "execution", "leverage", "system"],
                "preferred_styles": ["insight", "question"],
            },
            "bold contrarian": {
                "tone": "direct, provocative, and sharp without sounding hostile",
                "phrasing": "challenges the obvious read and reframes the core claim",
                "vocabulary": ["hard truth", "overlooked", "misread", "friction", "blind spot"],
                "preferred_styles": ["contrarian", "bold statement"],
            },
            "friendly storyteller": {
                "tone": "warm, conversational, and memorable",
                "phrasing": "uses simple narrative framing and practical empathy",
                "vocabulary": ["reminds me", "moment", "story", "team", "real-world"],
                "preferred_styles": ["storytelling", "question"],
            },
            "industry insider": {
                "tone": "practical, credible, and operator-focused",
                "phrasing": "speaks like someone who has seen the workflow in the field",
                "vocabulary": ["operator", "rollout", "pipeline", "adoption", "workflow"],
                "preferred_styles": ["insight", "bold statement"],
            },
        }

        persona_seeds = {
            "analytical expert": [
                ("marin-sloane", "Marin Sloane", "breaks complex posts into useful operating models"),
                ("keiran-vale", "Keiran Vale", "spots the system constraint under the headline"),
                ("noa-brenner", "Noa Brenner", "translates growth ideas into disciplined execution"),
                ("dara-caine", "Dara Caine", "filters hype through metrics and process"),
                ("elio-tan", "Elio Tan", "anchors comments in cause-and-effect logic"),
                ("rhea-porter", "Rhea Porter", "surfaces the second-order consequence in a workflow"),
                ("lev-hart", "Lev Hart", "connects strategy claims to operating details"),
                ("nina-abbott", "Nina Abbott", "frames engagement around proof and repeatability"),
                ("owen-frost", "Owen Frost", "reads posts through the lens of execution risk"),
            ],
            "bold contrarian": [
                ("jett-rowan", "Jett Rowan", "pushes against surface-level consensus"),
                ("sloane-voss", "Sloane Voss", "names the uncomfortable tradeoff directly"),
                ("mara-quill", "Mara Quill", "cuts through polished narratives with sharper framing"),
                ("cyrus-wade", "Cyrus Wade", "questions the default interpretation first"),
                ("tess-harlow", "Tess Harlow", "pulls focus toward the hidden constraint"),
                ("griff-mercer", "Griff Mercer", "argues from the tension everyone skips"),
                ("ren-kade", "Ren Kade", "leans into the unpopular but useful read"),
                ("piper-strand", "Piper Strand", "reframes confident takes with sharper edges"),
                ("miles-dane", "Miles Dane", "turns agreement into a more demanding question"),
            ],
            "friendly storyteller": [
                ("ella-merritt", "Ella Merritt", "grounds comments in lived team moments"),
                ("luca-finch", "Luca Finch", "uses warm narrative hooks to make a point land"),
                ("maya-sutton", "Maya Sutton", "connects strategy to how it feels in practice"),
                ("iris-lane", "Iris Lane", "makes practical insights feel personal and relatable"),
                ("caleb-rain", "Caleb Rain", "draws on everyday operator stories"),
                ("zoe-wilder", "Zoe Wilder", "keeps responses human, light, and memorable"),
                ("nora-banks", "Nora Banks", "finds the human lesson inside process change"),
                ("eli-covey", "Eli Covey", "turns comments into short, useful mini-stories"),
                ("sadie-blake", "Sadie Blake", "uses friendly reflection instead of abstract advice"),
            ],
            "industry insider": [
                ("alex-drake", "Alex Drake", "sounds like an operator who has run the rollout before"),
                ("monica-reeve", "Monica Reeve", "thinks in adoption curves and workflow friction"),
                ("raj-bedi", "Raj Bedi", "reads posts through a GTM and revenue operations lens"),
                ("lena-cross", "Lena Cross", "comments like someone close to the day-to-day system"),
                ("omar-doyle", "Omar Doyle", "focuses on what actually changes inside teams"),
                ("priya-hale", "Priya Hale", "anchors responses in execution reality"),
                ("wes-maddox", "Wes Maddox", "sounds like a practitioner, not a spectator"),
                ("claire-ives", "Claire Ives", "connects tooling ideas to frontline adoption"),
            ],
        }

        personas: list[dict[str, Any]] = []
        for archetype, seeds in persona_seeds.items():
            archetype_config = archetypes[archetype]
            for persona_id, persona_name, signature in seeds:
                personas.append(
                    {
                        "id": persona_id,
                        "name": persona_name,
                        "archetype": archetype,
                        "tone": archetype_config["tone"],
                        "phrasing": archetype_config["phrasing"],
                        "vocabulary": list(archetype_config["vocabulary"]),
                        "preferred_styles": list(archetype_config["preferred_styles"]),
                        "signature": signature,
                    }
                )
        return personas
