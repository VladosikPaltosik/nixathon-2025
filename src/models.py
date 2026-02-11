from __future__ import annotations

from pydantic import BaseModel


# --- Shared ---

class PlayerTower(BaseModel):
    playerId: int
    hp: int
    armor: int
    resources: int
    level: int


class EnemyTower(BaseModel):
    playerId: int
    hp: int
    armor: int
    level: int


class AttackAction(BaseModel):
    targetId: int
    troopCount: int


class CombatActionEntry(BaseModel):
    playerId: int
    action: AttackAction


# --- Negotiate ---

class DiplomacyProposal(BaseModel):
    allyId: int
    attackTargetId: int | None = None


class NegotiateRequest(BaseModel):
    gameId: int
    turn: int
    playerTower: PlayerTower
    enemyTowers: list[EnemyTower]
    combatActions: list[CombatActionEntry] = []


# --- Combat ---

class DiplomacyAction(BaseModel):
    allyId: int
    attackTargetId: int | None = None


class DiplomacyEntry(BaseModel):
    playerId: int
    action: DiplomacyAction


class CombatRequest(BaseModel):
    gameId: int
    turn: int
    playerTower: PlayerTower
    enemyTowers: list[EnemyTower]
    diplomacy: list[DiplomacyEntry] = []
    previousAttacks: list[CombatActionEntry] = []
