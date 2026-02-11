"""
Kingdom Wars AI Strategy - Version 2 (Defensive Rebalance)

Core philosophy:
1. Rush upgrades early (extended to turn 23) — resource advantage compounds hard.
2. Defense first — survival enables late-game dominance.
3. HP-adaptive strategy — scale aggression/defense based on current HP.
4. Smart retaliation — revenge when strong, defend when weak.
5. Focus fire — eliminating a player is worth more than spreading damage.
6. Diplomacy — gang up on the strongest threat.

Key improvements over v1:
- 100% armor coverage (was 60%)
- HP-aware defense scaling (higher armor when HP < 60)
- Reduced suicidal retaliation (bonus 50 vs 100)
- Better early armor (12 vs 5)
- Extended upgrade window (turn 23 vs 20)
"""

from __future__ import annotations

import math

from src.models import (
    CombatActionEntry,
    CombatRequest,
    DiplomacyEntry,
    EnemyTower,
    NegotiateRequest,
    PlayerTower,
)


# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

MAX_LEVEL = 5
FATIGUE_START = 25
# Approximate max game length (fatigue will end it)
GAME_HORIZON = 40


def upgrade_cost(level: int) -> int:
    """Cost to go from `level` to `level + 1`."""
    return math.ceil(50 * (1.75 ** (level - 1)))


def resource_gen(level: int) -> int:
    """Resources generated per turn at `level`."""
    return math.ceil(20 * (1.5 ** (level - 1)))


def effective_hp(t: EnemyTower | PlayerTower) -> int:
    return t.hp + t.armor


# ---------------------------------------------------------------------------
# Threat analysis
# ---------------------------------------------------------------------------

def _threat(enemy: EnemyTower, attacked_us: bool, troop_count: int = 0) -> float:
    """Higher = more dangerous. Used for target & alliance selection."""
    score = 0.0
    # Economy is the biggest long-term threat
    score += resource_gen(enemy.level) * 2.0
    # More HP = harder to kill
    score += enemy.hp * 0.3
    score += enemy.armor * 0.2
    # Direct retaliation weight
    if attacked_us:
        score += 40 + troop_count * 0.5
    return score


def _kill_cost(enemy: EnemyTower) -> int:
    """Resources needed to kill this enemy in one turn."""
    return enemy.hp + enemy.armor


# ---------------------------------------------------------------------------
# Negotiation strategy
# ---------------------------------------------------------------------------

def decide_negotiation(req: NegotiateRequest) -> list[dict]:
    """Return list of diplomacy proposals."""
    me = req.playerTower
    enemies = req.enemyTowers

    if not enemies:
        return []

    # Build attacker set from last turn's combat actions
    attackers: dict[int, int] = {}
    for ca in req.combatActions:
        if ca.action.targetId == me.playerId:
            attackers[ca.playerId] = ca.action.troopCount

    # Score threats
    scored = [
        (e, _threat(e, e.playerId in attackers, attackers.get(e.playerId, 0)))
        for e in enemies
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    biggest_threat = scored[0][0]

    # Propose alliance with everyone EXCEPT the biggest threat
    # Ask them all to attack the biggest threat
    proposals = []
    seen_allies: set[int] = set()

    for enemy, _ in scored:
        if enemy.playerId == biggest_threat.playerId:
            continue
        if enemy.playerId in seen_allies:
            continue
        seen_allies.add(enemy.playerId)
        proposals.append({
            "allyId": enemy.playerId,
            "attackTargetId": biggest_threat.playerId,
        })

    return proposals


# ---------------------------------------------------------------------------
# Combat strategy
# ---------------------------------------------------------------------------

def decide_combat(req: CombatRequest) -> list[dict]:
    """Return list of combat actions."""
    me = req.playerTower
    enemies = req.enemyTowers
    turn = req.turn

    if not enemies:
        return []

    actions: list[dict] = []
    budget = me.resources

    # --- Context ---
    attackers = _get_attackers(req.previousAttacks, me.playerId)
    allies = _get_allies(req.diplomacy, me.playerId)
    agreed_targets = _get_agreed_targets(req.diplomacy, me.playerId)

    # --- 1. UPGRADE decision ---
    budget = _maybe_upgrade(actions, me, turn, budget)

    # --- 2. ARMOR decision ---
    budget = _maybe_armor(actions, me, turn, budget, attackers, enemies)

    # --- 3. ATTACK decision ---
    budget = _decide_attacks(actions, enemies, budget, attackers, allies, agreed_targets, me)

    return actions


# ---------------------------------------------------------------------------
# Combat sub-decisions
# ---------------------------------------------------------------------------

def _maybe_upgrade(
    actions: list[dict],
    me: PlayerTower,
    turn: int,
    budget: int,
) -> int:
    if me.level >= MAX_LEVEL:
        return budget

    cost = upgrade_cost(me.level)
    if budget < cost:
        return budget

    turns_left = max(1, GAME_HORIZON - turn)
    extra_per_turn = resource_gen(me.level + 1) - resource_gen(me.level)
    payback_turns = cost / extra_per_turn if extra_per_turn else 999

    # Upgrade if it pays for itself within 60% of remaining game
    # Extended to turn 23 to maximize ROI before fatigue at turn 25
    if payback_turns < turns_left * 0.6 and turn <= 23:
        actions.append({"type": "upgrade"})
        budget -= cost

    return budget


def _maybe_armor(
    actions: list[dict],
    me: PlayerTower,
    turn: int,
    budget: int,
    attackers: dict[int, int],
    enemies: list[EnemyTower],
) -> int:
    if budget <= 0:
        return budget

    incoming_damage = sum(attackers.values())

    # Estimate potential incoming even if we weren't attacked last turn
    avg_enemy_resources = sum(resource_gen(e.level) for e in enemies) / max(len(enemies), 1)

    # HP-based defense multiplier: lower HP = more defensive
    hp_ratio = me.hp / 100.0

    if incoming_damage > 0:
        # Cover 100% of expected incoming (was 60%)
        # Cap increases with lower HP: from budget//2 to budget*0.7
        cap_multiplier = 0.5 + (1.0 - hp_ratio) * 0.2  # 0.5 to 0.7
        armor_amount = min(int(incoming_damage * 1.0), int(budget * cap_multiplier))
    elif turn <= 3:
        # Better early armor — increased from 5 to 12
        armor_amount = min(12, budget // 3)
    elif me.hp < 40:
        # Critical HP — go very defensive (60% of budget)
        armor_amount = min(int(avg_enemy_resources * 0.8), int(budget * 0.6))
    elif me.hp < 60:
        # Low HP — invest significantly more (50% of budget)
        armor_amount = min(int(avg_enemy_resources * 0.7), int(budget * 0.5))
    else:
        # Normal HP — moderate defense (35% of budget, was 20%)
        armor_amount = min(int(avg_enemy_resources * 0.4), int(budget * 0.35), 25)

    armor_amount = max(0, armor_amount)

    if armor_amount > 0:
        actions.append({"type": "armor", "amount": armor_amount})
        budget -= armor_amount

    return budget


def _decide_attacks(
    actions: list[dict],
    enemies: list[EnemyTower],
    budget: int,
    attackers: dict[int, int],
    allies: set[int],
    agreed_targets: set[int],
    me: PlayerTower,
) -> int:
    if budget <= 0 or not enemies:
        return budget

    # HP-based aggression: lower HP = less aggressive
    hp_ratio = me.hp / 100.0
    aggression_factor = 0.4 + hp_ratio * 0.6  # 0.4 to 1.0

    # Score each enemy for targeting
    target_scores: list[tuple[EnemyTower, float]] = []

    for e in enemies:
        score = 0.0

        # Retaliation — reduced from 100 to 50, scaled by HP
        if e.playerId in attackers:
            retaliation_bonus = (50 + attackers[e.playerId] * 1.2) * aggression_factor
            score += retaliation_bonus

        # Coordinated attack bonus
        if e.playerId in agreed_targets:
            score += 70

        # Don't attack allies (unless they hit us first)
        if e.playerId in allies and e.playerId not in attackers:
            score -= 300

        # Prefer killable targets (can we finish them this turn?)
        ehp = effective_hp(e)
        if ehp <= budget:
            score += 80  # huge bonus for securing a kill

        # Prefer weaker targets to eliminate faster
        score += 150.0 / (ehp + 1)

        # Higher-level enemies are more dangerous if left alive
        score += e.level * 8

        target_scores.append((e, score))

    target_scores.sort(key=lambda x: x[1], reverse=True)

    # Focus fire: dump most resources on primary target
    # But scale aggression with HP
    used_targets: set[int] = set()

    # Primary target budget: scale from 50% (low HP) to 75% (high HP)
    primary_budget_ratio = 0.5 + hp_ratio * 0.25

    for target, score in target_scores:
        if budget <= 0:
            break
        if score <= -100:
            # Very negative score = ally we shouldn't attack
            continue
        if target.playerId in used_targets:
            continue

        ehp = effective_hp(target)

        if len(used_targets) == 0:
            # Primary target: scaled by HP
            # If we can kill, spend enough to kill
            # Otherwise spend primary_budget_ratio of budget
            if ehp <= budget:
                spend = min(budget, ehp)
            else:
                spend = min(budget, int(budget * primary_budget_ratio))
        else:
            # Secondary target: spend the rest
            spend = budget

        if spend <= 0:
            continue

        actions.append({
            "type": "attack",
            "targetId": target.playerId,
            "troopCount": spend,
        })
        used_targets.add(target.playerId)
        budget -= spend

    return budget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_attackers(
    previous_attacks: list[CombatActionEntry],
    my_id: int,
) -> dict[int, int]:
    """Map of playerId → troopCount for players who attacked us."""
    result: dict[int, int] = {}
    for pa in previous_attacks:
        if pa.action.targetId == my_id:
            result[pa.playerId] = pa.action.troopCount
    return result


def _get_allies(
    diplomacy: list[DiplomacyEntry],
    my_id: int,
) -> set[int]:
    """Set of player IDs who declared us as ally this turn."""
    return {d.playerId for d in diplomacy if d.action.allyId == my_id}


def _get_agreed_targets(
    diplomacy: list[DiplomacyEntry],
    my_id: int,
) -> set[int]:
    """Targets that our allies suggested we attack together."""
    targets: set[int] = set()
    for d in diplomacy:
        if d.action.allyId == my_id and d.action.attackTargetId:
            targets.add(d.action.attackTargetId)
    return targets
