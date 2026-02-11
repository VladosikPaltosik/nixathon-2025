"""
Kingdom Wars AI Strategy

Core philosophy:
1. Rush upgrades early — resource advantage compounds hard.
2. Focus fire — eliminating a player is worth more than spreading damage.
3. Diplomacy — gang up on the strongest threat.
4. Armor is cheap insurance when being targeted.
5. Late-game: pure aggression before fatigue kills everyone.
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
    budget = _decide_attacks(actions, enemies, budget, attackers, allies, agreed_targets)

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
    # and we're not in super-late game
    if payback_turns < turns_left * 0.6 and turn <= 20:
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
    # (someone might start targeting us)
    avg_enemy_resources = sum(resource_gen(e.level) for e in enemies) / max(len(enemies), 1)

    if incoming_damage > 0:
        # Cover ~60% of expected incoming
        armor_amount = min(int(incoming_damage * 0.6), budget // 3)
    elif turn <= 3:
        # Minimal early armor — save for upgrade
        armor_amount = min(5, budget // 4)
    elif me.hp < 50:
        # Low HP — invest more in armor
        armor_amount = min(int(avg_enemy_resources * 0.5), budget // 3)
    else:
        # Light defensive buffer
        armor_amount = min(int(avg_enemy_resources * 0.25), budget // 5, 15)

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
) -> int:
    if budget <= 0 or not enemies:
        return budget

    # Score each enemy for targeting
    target_scores: list[tuple[EnemyTower, float]] = []

    for e in enemies:
        score = 0.0

        # Retaliation — strong incentive
        if e.playerId in attackers:
            score += 100 + attackers[e.playerId] * 1.5

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
    used_targets: set[int] = set()

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
            # Primary target: go all-in, or at least enough to kill
            spend = min(budget, max(ehp, int(budget * 0.75)))
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
