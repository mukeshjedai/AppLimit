from __future__ import annotations

import pytest
from fastapi import HTTPException

from applimit import web


def test_flashcard_deck_accepts_common_json_keys() -> None:
    cards = web._normalize_flashcard_deck(
        [
            {"front": "Cell", "back": "Basic unit of life"},
            {"question": "Capital of France?", "answer": "Paris"},
            {"term": "Photon", "definition": "A quantum of light"},
        ]
    )
    assert len(cards) == 3
    assert cards[1]["front"] == "Capital of France?"
    assert cards[2]["back"] == "A quantum of light"
    assert all(card["id"] for card in cards)


def test_flashcard_deck_rejects_missing_back() -> None:
    with pytest.raises(HTTPException) as error:
        web._normalize_flashcard_deck([{"front": "Incomplete"}])
    assert error.value.status_code == 400


def test_flashcard_progress_is_saved_per_user(monkeypatch: pytest.MonkeyPatch) -> None:
    cards = web._normalize_flashcard_deck([{"front": "Q", "back": "A"}])
    deck = {
        "id": "deck1",
        "page_type": "flashcard_deck",
        "title": "Test deck",
        "flashcard_cards": cards,
        "flashcard_statuses": {},
    }
    monkeypatch.setattr(web, "_store_get", lambda *_args, **_kwargs: (deck, "local", None))
    monkeypatch.setattr(web, "_store_save", lambda value, **_kwargs: (value, "local", None))

    result = web.save_flashcard_deck_status(
        "deck1",
        web.FlashcardDeckStatusRequest(
            user_email="reader@example.com",
            current_index=0,
            seen_card_ids=[cards[0]["id"]],
            mastered_card_ids=[cards[0]["id"]],
        ),
    )

    assert result["deck"]["seen_count"] == 1
    assert result["deck"]["mastered_count"] == 1
    assert result["deck"]["progress_percent"] == 100
    assert result["deck"]["completed"] is True
