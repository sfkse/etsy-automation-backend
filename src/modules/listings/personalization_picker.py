"""
Personalization Picker (Section E of OPERATIONAL_INTEGRATION.md).

Maps a user-facing personalization choice label (e.g. "Single Birthstone +
Initial") to a PersonalizationTemplate row via the template's stored
type_signature JSON.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import PersonalizationTemplate


class PersonalizationPicker:
    """Resolves a user-facing choice label to a PersonalizationTemplate."""

    USER_FACING_OPTIONS: list[tuple[str, dict]] = [
        ("None",                          {"none": True}),
        ("Single Birthstone + Initial",   {"has_initial": True, "has_birthstone": True, "count": 1}),
        ("Multi (2-3) Birthstones",       {"has_initial": True, "has_birthstone": True, "count_max": 3}),
        ("Multi (4-5) Birthstones",       {"has_initial": True, "has_birthstone": True, "count_max": 5}),
        ("Single Birth Flower + Initial", {"has_initial": True, "has_flower": True, "count": 1}),
        ("Multi (2-3) Birth Flowers",     {"has_initial": True, "has_flower": True, "count_max": 3}),
        ("Name Only",                     {"has_name": True, "count": 1}),
        ("Name + Date",                   {"has_name": True, "has_date": True}),
        ("Custom Text",                   {"has_custom_text": True}),
    ]

    def __init__(self, session: Session) -> None:
        self.session = session

    def pick(
        self,
        user_choice_label: str,
        category: str,
    ) -> Optional[PersonalizationTemplate]:
        """
        Return the PersonalizationTemplate matching the user's choice and
        applicable to *category*. Returns None if the choice is "None" or
        cannot be resolved.
        """
        signature = dict(self.USER_FACING_OPTIONS).get(user_choice_label)
        if signature is None or signature.get("none"):
            return None

        candidates = (
            self.session.query(PersonalizationTemplate)
            .all()
        )
        for candidate in candidates:
            applicable = candidate.applicable_categories or []
            if category not in applicable:
                continue
            if self._signature_matches(candidate.type_signature or {}, signature):
                return candidate
        return None

    @staticmethod
    def _signature_matches(template_sig: dict, target_sig: dict) -> bool:
        for key, value in target_sig.items():
            if template_sig.get(key) != value:
                return False
        return True
