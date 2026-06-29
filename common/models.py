"""Shared data structures used by both scrapers and the report.

All odds are DECIMAL odds (e.g. 2.5 means 6/4). `None` means no price available.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Fixture:
    """A single match. `kickoff` is timezone-aware UTC."""
    home: str
    away: str
    kickoff: datetime


@dataclass
class MatchOdds:
    """1X2 decimal odds."""
    home: Optional[float] = None
    draw: Optional[float] = None
    away: Optional[float] = None


@dataclass
class BetfairGame:
    """Betfair Exchange view of one fixture."""
    fixture: Fixture
    match_odds: MatchOdds = field(default_factory=MatchOdds)
    # scoreline string "h-a" (e.g. "2-1") -> decimal odds.
    # May also include bucket runners like "Any Other Home Win".
    correct_score: dict[str, Optional[float]] = field(default_factory=dict)


@dataclass(frozen=True)
class UserPrediction:
    user_id: int
    user_name: str
    home_goals: int
    away_goals: int
    rank: Optional[int] = None  # leaderboard position when fetched (1 = top)

    @property
    def score(self) -> str:
        return f"{self.home_goals}-{self.away_goals}"

    @property
    def outcome(self) -> str:
        if self.home_goals > self.away_goals:
            return "HOME"
        if self.home_goals < self.away_goals:
            return "AWAY"
        return "DRAW"


@dataclass
class CrowdGame:
    """topcorner.org crowd view of one fixture: every user's predicted score,
    plus the actual result once the game has been played."""
    fixture: Fixture
    predictions: list[UserPrediction] = field(default_factory=list)
    played: bool = False
    final_home: Optional[int] = None
    final_away: Optional[int] = None
    # 1-based position in the tournament schedule (kickoff order).
    number: Optional[int] = None

    @property
    def n(self) -> int:
        return len(self.predictions)

    def score_distribution(self) -> Counter:
        """Counter of "h-a" scoreline -> number of users predicting it."""
        return Counter(p.score for p in self.predictions)

    def outcome_distribution(self) -> Counter:
        """Counter of HOME/DRAW/AWAY -> number of users."""
        return Counter(p.outcome for p in self.predictions)

    def modal_score(self) -> Optional[tuple[str, int]]:
        dist = self.score_distribution()
        if not dist:
            return None
        return dist.most_common(1)[0]

    @property
    def final_score(self) -> Optional[str]:
        if self.final_home is None or self.final_away is None:
            return None
        return f"{self.final_home}-{self.final_away}"

    @property
    def final_outcome(self) -> Optional[str]:
        if self.final_home is None or self.final_away is None:
            return None
        if self.final_home > self.final_away:
            return "HOME"
        if self.final_home < self.final_away:
            return "AWAY"
        return "DRAW"

    def exact_correct(self) -> int:
        """How many users predicted the exact final scoreline."""
        target = self.final_score
        if target is None:
            return 0
        return sum(1 for p in self.predictions if p.score == target)

    def outcome_correct(self) -> int:
        """How many users predicted the correct result (home/draw/away)."""
        target = self.final_outcome
        if target is None:
            return 0
        return sum(1 for p in self.predictions if p.outcome == target)
