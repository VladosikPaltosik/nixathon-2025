"""
Kingdom Wars AI Strategy - Version 3.3 (Stealth Economy + Adaptive Tactics)

Core philosophy:
1. STEALTH ECONOMY — Be #2 in level while 4+ players alive (don't be the biggest threat)
2. ECONOMY FIRST — No attacks until Level 3, focus purely on upgrades
3. SURVIVAL TARGET — Maintain HP + Armor >= 120 during early game (adaptive: up to 150 under heavy attack)
4. OPPORTUNISTIC AGGRESSION — After Level 3, if not attacked: 60% offense, 20% defense, 20% save
5. ADAPTIVE DEFENSE — Analyze attack intensity and boost armor spending accordingly when threatened
6. HP-adaptive strategy — scale aggression/defense based on current HP
7. Focus fire — eliminating a player is worth more than spreading damage
8. SMART DIPLOMACY:
   - Level < 3: Offer friendship to ALL players (protect economy phase)
   - Level >= 3: Coordinate attacks on WEAKEST player (quick elimination)

Combat Modes:
- ECONOMY MODE (Level < 3): 0% attack, 70-85% armor, rest upgrades
- AGGRESSIVE MODE (Level 3+, not attacked, 3+ alive): 60% attack, 20% armor, 20% save
- DEFENSIVE MODE (Level 3+, under attack): 20-40% attack, 50-95% armor

Key improvements over v2:
- Zero attacks before Level 3 (was: saving mode with exceptions)
- HP + Armor >= 120-150 guarantee (adaptive based on incoming threats)
- Increased defensive spending after Level 3 (50-70% armor budget)
- Extended upgrade window (turn 23 vs 20)

New in v3.1:
- Attack intensity analysis: detects coordinated attacks and heavy damage
- Adaptive armor boost: +15-25% extra budget on armor when heavily attacked
- Threat-based HP targets: 120 normal, 135 medium threat, 150 high threat
- Dynamic coverage: 100-120% incoming damage coverage based on threat level

New in v3.2:
- Aggressive mode: capitalize on safe position with 60% offense when not attacked
- Resource saving: 20% budget reserved for future turns in aggressive mode
- Increased aggression factor: 0.7-1.0 in aggressive mode vs 0.3-0.8 in defensive
- Smarter budget allocation: adapt spending based on threat level

New in v3.3:
- Stealth upgrade strategy: stay at #2 level position while 4+ players alive
- Avoid being the biggest threat: don't upgrade if already highest level (solo)
- Resource accumulation: save coins when not upgrading for strategic opportunities
- Level position tracking: monitor our rank among all alive players
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
    """
    Higher = more dangerous. Used for target & alliance selection.
    Reserved for future advanced targeting logic.
    """
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


def _get_level_position(me: PlayerTower, enemies: list[EnemyTower]) -> tuple[int, int, int]:
    """
    Determine our position in level ranking.
    Returns: (our_rank, highest_level, num_alive)
    - our_rank: 1 = highest, 2 = second highest, etc.
    - highest_level: the maximum level among all alive players
    - num_alive: number of alive players (including us)
    """
    alive_enemies = [e for e in enemies if e.hp > 0]

    # Get all levels including ours
    all_levels = [me.level] + [e.level for e in alive_enemies]
    all_levels_sorted = sorted(all_levels, reverse=True)

    # Find our rank (1-indexed)
    our_rank = all_levels_sorted.index(me.level) + 1

    # Highest level among all
    highest_level = all_levels_sorted[0]

    # Total alive players
    num_alive = len(alive_enemies) + 1  # +1 for us

    return (our_rank, highest_level, num_alive)


# ---------------------------------------------------------------------------
# Negotiation strategy
# ---------------------------------------------------------------------------

def decide_negotiation(req: NegotiateRequest) -> list[dict]:
    """
    Return list of diplomacy proposals.

    Strategy:
    - Level < 3 (Economy mode): Offer friendship to ALL players (no attack target)
    - Level >= 3: Coordinate attacks on the WEAKEST player (easiest to eliminate)
    """
    me = req.playerTower
    enemies = req.enemyTowers

    if not enemies:
        return []

    # Filter out dead enemies
    alive_enemies = [e for e in enemies if e.hp > 0]
    if not alive_enemies:
        return []

    proposals = []

    # ECONOMY MODE (Level < 3): Offer friendship to everyone
    if me.level < 3:
        # Send friendship offers to all alive enemies
        for enemy in alive_enemies:
            proposals.append({
                "allyId": enemy.playerId,
                "attackTargetId": None,  # No attack target = peace offer
            })

    # AGGRESSIVE/DEFENSIVE MODE (Level >= 3): Gang up on weakest
    else:
        # Find the weakest enemy (lowest effective HP)
        weakest = min(alive_enemies, key=lambda e: effective_hp(e))

        # Propose alliance with everyone EXCEPT the weakest
        # Ask them all to attack the weakest target
        for enemy in alive_enemies:
            if enemy.playerId == weakest.playerId:
                continue  # Don't ally with our target

            proposals.append({
                "allyId": enemy.playerId,
                "attackTargetId": weakest.playerId,
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

    # Count alive enemies
    alive_enemies = [e for e in enemies if e.hp > 0]
    num_alive = len(alive_enemies)

    # --- Determine combat mode ---
    # ECONOMY MODE: Level < 3 - pure economy, no attacks
    economy_mode = me.level < 3

    # AGGRESSIVE MODE: Level 3+, not attacked, 3+ players alive
    # When we're safe (not attacked), capitalize on advantage
    # 60% attack, 20% armor, 20% save for future
    aggressive_mode = (
        me.level >= 3 and
        len(attackers) == 0 and
        num_alive >= 2  # At least 2 other players alive
    )

    # --- 1. UPGRADE decision ---
    budget = _maybe_upgrade(actions, me, turn, budget, enemies)

    # --- 2. ARMOR decision ---
    budget = _maybe_armor(actions, me, budget, attackers, enemies, economy_mode, aggressive_mode)

    # --- 3. ATTACK decision ---
    budget = _decide_attacks(actions, enemies, budget, attackers, allies, agreed_targets, me, economy_mode, aggressive_mode)

    return actions


# ---------------------------------------------------------------------------
# Combat sub-decisions
# ---------------------------------------------------------------------------

def _maybe_upgrade(
    actions: list[dict],
    me: PlayerTower,
    turn: int,
    budget: int,
    enemies: list[EnemyTower],
) -> int:
    if me.level >= MAX_LEVEL:
        return budget

    cost = upgrade_cost(me.level)
    if budget < cost:
        return budget

    # Get our level position
    our_rank, highest_level, num_alive = _get_level_position(me, enemies)

    # STEALTH STRATEGY: Be second in level while 4+ players alive
    # If we're already #1 (highest level), DON'T upgrade - stay under the radar
    # Exception: if multiple players at highest level, we can upgrade
    if num_alive >= 4:
        # Count how many players are at the highest level
        alive_enemies = [e for e in enemies if e.hp > 0]
        players_at_highest = sum(1 for e in alive_enemies if e.level == highest_level)
        if me.level == highest_level:
            players_at_highest += 1  # Include us

        # If we're the ONLY one at highest level, don't upgrade (be #2)
        if our_rank == 1 and players_at_highest == 1:
            # Save money instead of upgrading
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


def _analyze_attack_intensity(attackers: dict[int, int], enemies: list[EnemyTower]) -> dict:
    """
    Analyze how intensely we were attacked to determine defense boost.
    Returns dict with metrics about the attack intensity.

    Example scenarios:
    - 1 player attacks with 15 troops → LOW threat → +0% armor budget
    - 2 players attack with 30 troops total → MEDIUM threat → +15% armor budget
    - 3 players attack with 60 troops total → HIGH threat → +25% armor budget

    This allows us to survive coordinated attacks by automatically boosting defense.
    """
    num_attackers = len(attackers)
    total_damage = sum(attackers.values())

    alive_enemies = [e for e in enemies if e.hp > 0]
    num_alive = max(len(alive_enemies), 1)

    # Calculate intensity metrics
    attacker_ratio = num_attackers / num_alive if num_alive > 0 else 0  # % of players attacking us
    avg_damage_per_attacker = total_damage / num_attackers if num_attackers > 0 else 0

    # Threat levels:
    # - HIGH: 50%+ of players attacking us OR massive damage (60+ troops)
    # - MEDIUM: 2+ players attacking OR 30+ troops
    # - LOW: 1 player or small damage

    is_high_threat = (attacker_ratio >= 0.5 or total_damage >= 60)
    is_medium_threat = (num_attackers >= 2 or total_damage >= 30)

    # Defense boost multiplier (how much extra % of budget to spend on armor)
    defense_boost = 0.0
    if is_high_threat:
        defense_boost = 0.25  # +25% budget on armor
    elif is_medium_threat:
        defense_boost = 0.15  # +15% budget on armor
    else:
        defense_boost = 0.0   # No extra boost

    return {
        "num_attackers": num_attackers,
        "total_damage": total_damage,
        "attacker_ratio": attacker_ratio,
        "avg_damage": avg_damage_per_attacker,
        "is_high_threat": is_high_threat,
        "is_medium_threat": is_medium_threat,
        "defense_boost": defense_boost,
    }


def _maybe_armor(
    actions: list[dict],
    me: PlayerTower,
    budget: int,
    attackers: dict[int, int],
    enemies: list[EnemyTower],
    economy_mode: bool = False,
    aggressive_mode: bool = False,
) -> int:
    if budget <= 0:
        return budget

    incoming_damage = sum(attackers.values())

    # Analyze attack intensity for adaptive defense
    attack_analysis = _analyze_attack_intensity(attackers, enemies)

    # Estimate potential incoming even if we weren't attacked last turn (ignore dead enemies)
    alive_enemies = [e for e in enemies if e.hp > 0]
    avg_enemy_resources = sum(resource_gen(e.level) for e in alive_enemies) / max(len(alive_enemies), 1)

    # HP-based defense multiplier: lower HP = more defensive
    hp_ratio = me.hp / 100.0

    # AGGRESSIVE MODE (Level 3+, not attacked, 3+ players): Minimal defense, focus on offense
    if aggressive_mode:
        # Only spend 20% on armor - we're capitalizing on being safe
        armor_amount = int(budget * 0.2)

    # ECONOMY MODE (Level < 3): Guarantee HP + Armor >= 120
    elif economy_mode:
        # Target: maintain total effective HP of 120
        # If heavily attacked, increase target
        BASE_TARGET_HP = 120

        # Increase target if being coordinated attacked
        if attack_analysis["is_high_threat"]:
            TARGET_TOTAL_HP = BASE_TARGET_HP + 30  # 150 total HP under heavy attack
        elif attack_analysis["is_medium_threat"]:
            TARGET_TOTAL_HP = BASE_TARGET_HP + 15  # 135 total HP under medium attack
        else:
            TARGET_TOTAL_HP = BASE_TARGET_HP

        current_total_hp = me.hp + me.armor
        needed_armor = max(0, TARGET_TOTAL_HP - current_total_hp)

        if incoming_damage > 0:
            # Take the maximum of: needed for target HP or 110% incoming damage (cover + buffer)
            armor_amount = max(needed_armor, int(incoming_damage * 1.1))
        else:
            # Just get to target total HP
            armor_amount = needed_armor

        # Cap at 70-85% of budget depending on threat (leave room for upgrades)
        cap_ratio = 0.7 + (attack_analysis["defense_boost"] * 0.6)  # 0.7 to 0.85
        armor_amount = min(armor_amount, int(budget * cap_ratio))

    # LEVEL 3+ MODE: More defensive focus with adaptive boost
    elif incoming_damage > 0:
        # Cover 100-120% of expected incoming (more if heavily attacked)
        coverage_ratio = 1.0 + (attack_analysis["defense_boost"] * 0.8)  # 1.0 to 1.2

        # Base cap: 0.6 to 0.8 based on HP
        # Add defense boost for intensive attacks
        base_cap = 0.6 + (1.0 - hp_ratio) * 0.2  # 0.6 to 0.8
        cap_multiplier = min(0.9, base_cap + attack_analysis["defense_boost"])  # up to 0.9

        armor_amount = min(int(incoming_damage * coverage_ratio), int(budget * cap_multiplier))
    elif me.hp < 40:
        # Critical HP — go very defensive (70-80% of budget based on threat)
        cap_ratio = 0.7 + attack_analysis["defense_boost"]  # 0.7 to 0.95
        armor_amount = min(int(avg_enemy_resources * 1.0), int(budget * cap_ratio))
    elif me.hp < 60:
        # Low HP — invest significantly more (60-75% of budget based on threat)
        cap_ratio = 0.6 + attack_analysis["defense_boost"]  # 0.6 to 0.85
        armor_amount = min(int(avg_enemy_resources * 0.8), int(budget * cap_ratio))
    else:
        # Normal HP — higher defense (50-65% of budget based on threat)
        cap_ratio = 0.5 + attack_analysis["defense_boost"]  # 0.5 to 0.75
        armor_amount = min(int(avg_enemy_resources * 0.5), int(budget * cap_ratio))

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
    economy_mode: bool = False,
    aggressive_mode: bool = False,
) -> int:
    if budget <= 0 or not enemies:
        return budget

    # ECONOMY MODE (Level < 3): NO ATTACKS - focus purely on upgrades
    # Zero attacks to maximize upgrade speed and reach Level 3 ASAP
    if economy_mode:
        return budget

    # AGGRESSIVE MODE: Use 60% of original budget for attacks, save 20%
    if aggressive_mode:
        # Calculate 60% of total budget for attacks (20% already spent on armor)
        original_budget = budget / 0.8  # Reverse calculate original budget
        attack_budget = int(original_budget * 0.6)

        # Use attack_budget for attacks, save the rest (20% automatically saved)
        budget_to_use = min(attack_budget, budget)
        remaining_budget = budget - budget_to_use

        # Perform attacks with increased aggression
        hp_ratio = me.hp / 100.0
        aggression_factor = 0.7 + hp_ratio * 0.3  # 0.7 to 1.0 (more aggressive)
    else:
        # DEFENSIVE MODE: Normal behavior
        budget_to_use = budget
        remaining_budget = 0

        # HP-based aggression: lower HP = less aggressive
        # Reduced aggression for more defensive playstyle after Level 3
        hp_ratio = me.hp / 100.0
        aggression_factor = 0.3 + hp_ratio * 0.5  # 0.3 to 0.8 (was 0.4 to 1.0)

    # Score each enemy for targeting
    target_scores: list[tuple[EnemyTower, float]] = []

    for e in enemies:
        # Skip dead enemies - don't waste resources on eliminated players
        if e.hp <= 0:
            continue

        score = 0.0

        # Retaliation — reduced from 50 to 30, scaled by HP for defensive playstyle
        if e.playerId in attackers:
            retaliation_bonus = (30 + attackers[e.playerId] * 1.0) * aggression_factor
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
    # But scale aggression with HP (reduced for defensive playstyle)
    used_targets: set[int] = set()

    # Primary target budget: scale from 40% (low HP) to 60% (high HP) - was 50% to 75%
    # In aggressive mode, be more willing to go all-in
    if aggressive_mode:
        primary_budget_ratio = 0.6 + hp_ratio * 0.3  # 0.6 to 0.9
    else:
        primary_budget_ratio = 0.4 + hp_ratio * 0.2  # 0.4 to 0.6

    for target, score in target_scores:
        if budget_to_use <= 0:
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
            if ehp <= budget_to_use:
                spend = min(budget_to_use, ehp)
            else:
                spend = min(budget_to_use, int(budget_to_use * primary_budget_ratio))
        else:
            # Secondary target: spend the rest
            spend = budget_to_use

        if spend <= 0:
            continue

        actions.append({
            "type": "attack",
            "targetId": target.playerId,
            "troopCount": spend,
        })
        used_targets.add(target.playerId)
        budget_to_use -= spend

    # Return remaining budget (includes saved budget in aggressive mode)
    return remaining_budget


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
