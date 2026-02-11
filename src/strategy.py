"""
Kingdom Wars AI Strategy - Version 3.7 (Patient Assassin)

Core philosophy:
1. DEFENSE PRIORITY (Level 3+, 3+ players) — 60-80% armor, save rest for one-shot kills
2. DUEL MODE — When 2 players left: no upgrades, 50-80% defense, 100% attack with remaining
3. ENHANCED SURVIVAL — Maintain HP + Armor >= 130 (early), >= 150 (Level 3+)
4. PATIENT ONE-SHOT — Accumulate 40% budget until can eliminate weakest in single strike
5. RESOURCE INTELLIGENCE — Track all enemy resources and spending patterns
6. COUNTER-STRATEGY — Detect and counter turtle (pure defense) and hoarder (burst attack) strategies
7. STEALTH ECONOMY — Be #2 in level while 4+ players alive (don't be the biggest threat)
8. ECONOMY FIRST — No attacks until Level 3, focus purely on upgrades
9. MINIMAL AGGRESSION — Only attack when can one-shot OR light retaliation (20% budget)
10. ADAPTIVE DEFENSE — Analyze attack intensity and boost armor spending accordingly when threatened
11. SMART DIPLOMACY:
   - Level < 3: Offer friendship to ALL players (protect economy phase)
   - Level >= 3: Coordinate attacks on WEAKEST player (quick elimination)

Combat Modes:
- ECONOMY MODE (Level < 3): 0% attack, 70-85% armor, rest upgrades
- LEVEL 3+ DEFENSIVE MODE (3+ players): 60-80% armor, save 40% for one-shot kills
  - Can one-shot: 100% remaining budget on kill target
  - Saving for kill: 0-20% attack (retaliation only), save 80%
  - Normal: 20% attack (pressure), save 80%
- DUEL MODE (2 players): NO upgrades, 50-80% armor, 100% attack (remaining budget)

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

New in v3.4:
- Enemy resource estimation: track spending patterns and estimate current resources
- Turtle detection: identify pure-defense players and avoid wasting attacks on them
- Hoarder detection: identify players saving resources for burst attacks
- Adaptive armor scaling: increase defense by +20% per detected hoarder
- Smart targeting: deprioritize turtles (-200 score), prioritize hoarders (+40 score)
- Max threat calculation: defend against potential burst damage from all enemies

New in v3.5:
- Increased survival thresholds: 130 HP (early), 150 HP (Level 3+) - up from 120
- One-shot kill strategy: accumulate resources to eliminate weakest in single turn
- Save for kill mode: minimal attacks when within 2x budget of kill threshold
- Kill target priority: +500 score bonus for guaranteed elimination
- Guaranteed minimum armor: always reach survival threshold before attacking

New in v3.6:
- Duel mode detection: automatically activate when 2 players remain
- No upgrades in duel: all resources to immediate combat (won't ROI in time)
- Duel armor strategy: 50-80% budget based on HP (balanced defense/offense)
- Duel attack strategy: 100% of remaining budget (max aggression)
- Aggression factor: 1.0 in duel (maximum) vs 0.3-0.8 in normal mode

New in v3.7:
- Defense priority after Level 3: 60-80% armor (was aggressive 60% attack)
- Patient accumulation: save 40% of budget for one-shot opportunities
- Conditional attacks: only attack when can one-shot OR light retaliation (20%)
- Removed aggressive mode: replaced with defensive save-for-kill strategy
- Zero waste: accumulate until guaranteed elimination, no chip damage
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


def _estimate_enemy_resources(
    enemy: EnemyTower,
    previous_attacks: list[CombatActionEntry],
    turn: int,
) -> dict:
    """
    Estimate enemy's current resources based on their spending patterns.

    Returns dict with:
    - estimated_resources: likely current coins
    - spending_last_turn: how much they spent
    - is_hoarding: True if they're saving coins (dangerous!)
    - is_turtle: True if they spend everything on armor
    - threat_level: estimated max attack they can do
    """
    # Calculate their income per turn
    income = resource_gen(enemy.level)

    # Find their spending in previous turn
    spending_last_turn = 0
    for attack in previous_attacks:
        if attack.playerId == enemy.playerId:
            spending_last_turn += attack.action.troopCount

    # If they spent very little, they likely have more saved
    spend_ratio = spending_last_turn / max(income, 1)

    if spend_ratio < 0.3:
        # Hoarding: they spent <30% of income
        estimated_resources = int(income * 2.5)  # Assume 2.5 turns saved
        is_hoarding = True
    elif spend_ratio < 0.6:
        # Moderate spending
        estimated_resources = int(income * 1.5)
        is_hoarding = False
    else:
        # Heavy spending
        estimated_resources = income
        is_hoarding = False

    # Check if they're "turtle" (all defense, no attacks)
    is_turtle = (spending_last_turn == 0 and turn > 5)

    # Threat level: maximum damage they could do
    # If hoarding, they could unleash everything
    threat_level = estimated_resources if is_hoarding else income

    return {
        "estimated_resources": estimated_resources,
        "spending_last_turn": spending_last_turn,
        "is_hoarding": is_hoarding,
        "is_turtle": is_turtle,
        "threat_level": threat_level,
        "income": income,
    }


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

    # DUEL MODE: Only 2 players left (us + 1 enemy) - all resources to combat
    # No upgrades, maximum defense, all-in attacks
    duel_mode = (num_alive == 2)

    # LEVEL 3+ MODE (not duel): Defense priority + save for one-shot
    # 60%+ armor (priority), 40% save for kill
    level3_defensive_mode = (
        me.level >= 3 and
        not economy_mode and
        not duel_mode
    )

    # --- 1. UPGRADE decision ---
    budget = _maybe_upgrade(actions, me, turn, budget, enemies)

    # --- 2. ARMOR decision ---
    budget = _maybe_armor(actions, me, budget, attackers, enemies, economy_mode, level3_defensive_mode, duel_mode, turn, req.previousAttacks)

    # --- 3. ATTACK decision ---
    budget = _decide_attacks(actions, enemies, budget, attackers, allies, agreed_targets, me, economy_mode, level3_defensive_mode, duel_mode, turn, req.previousAttacks)

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

    # DUEL MODE: Don't upgrade - won't have time to ROI
    # Use all resources for immediate combat instead
    if num_alive == 2:
        return budget  # Skip upgrade in 1v1

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
    level3_defensive_mode: bool = False,
    duel_mode: bool = False,
    turn: int = 0,
    previous_attacks: list[CombatActionEntry] = None,
) -> int:
    if budget <= 0:
        return budget

    if previous_attacks is None:
        previous_attacks = []

    incoming_damage = sum(attackers.values())

    # Analyze attack intensity for adaptive defense
    attack_analysis = _analyze_attack_intensity(attackers, enemies)

    # Estimate potential incoming even if we weren't attacked last turn (ignore dead enemies)
    alive_enemies = [e for e in enemies if e.hp > 0]
    avg_enemy_resources = sum(resource_gen(e.level) for e in alive_enemies) / max(len(alive_enemies), 1)

    # CRITICAL: Check for hoarders and calculate max potential threat
    max_threat = 0
    num_hoarders = 0
    for enemy in alive_enemies:
        enemy_analysis = _estimate_enemy_resources(enemy, previous_attacks, turn)
        if enemy_analysis["is_hoarding"]:
            num_hoarders += 1
            max_threat += enemy_analysis["threat_level"]
        else:
            max_threat += enemy_analysis["income"]

    # If there are hoarders, increase our defensive stance
    hoarder_multiplier = 1.0 + (num_hoarders * 0.2)  # +20% per hoarder

    # HP-based defense multiplier: lower HP = more defensive
    hp_ratio = me.hp / 100.0

    # DUEL MODE (2 players): Maximum defense - all-in survival
    if duel_mode:
        # In duel, spend 50-70% on armor depending on HP
        # Need to balance defense with attack
        if me.hp < 40:
            armor_ratio = 0.7  # Critical HP - very defensive
        elif me.hp < 60:
            armor_ratio = 0.6  # Low HP - defensive
        else:
            armor_ratio = 0.5  # Normal HP - balanced

        # If being attacked, cover 100% of incoming
        if incoming_damage > 0:
            armor_amount = max(int(incoming_damage), int(budget * armor_ratio))
        else:
            # Prepare for enemy's max possible attack
            armor_amount = int(budget * armor_ratio)

        armor_amount = min(armor_amount, int(budget * 0.8))  # Cap at 80% to leave room for attack

    # LEVEL 3+ DEFENSIVE MODE: Defense priority - 60%+ armor, save rest for one-shot
    elif level3_defensive_mode:
        # Always spend 60%+ on armor (can be more if needed for 150 HP or threats)
        base_armor_ratio = 0.6

        # Increase if hoarders present
        if num_hoarders > 0:
            base_armor_ratio = min(0.8, 0.6 + (num_hoarders * 0.1))  # Up to 80%

        # Ensure we reach 150 HP minimum
        LEVEL3_TARGET_HP = 150
        current_total_hp = me.hp + me.armor
        needed_for_target = max(0, LEVEL3_TARGET_HP - current_total_hp)

        # If incoming damage, cover it + reach 150
        if incoming_damage > 0:
            coverage = int(incoming_damage * hoarder_multiplier)
            armor_amount = max(needed_for_target, coverage, int(budget * base_armor_ratio))
        else:
            # No incoming - just maintain 150 HP + prepare for potential attacks
            estimated_threat = int(max_threat * 0.3) if num_hoarders > 0 else int(avg_enemy_resources * 0.5)
            armor_amount = max(needed_for_target, estimated_threat, int(budget * base_armor_ratio))

        # Cap at 80% to leave 20% minimum for potential attacks
        armor_amount = min(armor_amount, int(budget * 0.8))

    # ECONOMY MODE (Level < 3): Guarantee HP + Armor >= 130 (increased from 120)
    elif economy_mode:
        # Target: maintain total effective HP of 130 minimum
        # If heavily attacked, increase target
        BASE_TARGET_HP = 130  # Increased from 120 for better survival

        # Increase target if being coordinated attacked OR hoarders detected
        if attack_analysis["is_high_threat"] or num_hoarders >= 2:
            TARGET_TOTAL_HP = BASE_TARGET_HP + 40  # 170 total HP
        elif attack_analysis["is_medium_threat"] or num_hoarders >= 1:
            TARGET_TOTAL_HP = BASE_TARGET_HP + 20  # 150 total HP
        else:
            TARGET_TOTAL_HP = BASE_TARGET_HP

        current_total_hp = me.hp + me.armor
        needed_armor = max(0, TARGET_TOTAL_HP - current_total_hp)

        # CRITICAL: If hoarders detected, prepare for burst
        if num_hoarders > 0 and incoming_damage == 0:
            # No current attack, but hoarders might strike next turn
            # Defend against 50% of max_threat
            preemptive_armor = int(max_threat * 0.5)
            needed_armor = max(needed_armor, preemptive_armor)

        if incoming_damage > 0:
            # Take the maximum of: needed for target HP or 110% incoming damage (cover + buffer)
            armor_amount = max(needed_armor, int(incoming_damage * 1.1 * hoarder_multiplier))
        else:
            # Just get to target total HP (or preemptive hoarder defense)
            armor_amount = needed_armor

        # Cap at 70-90% of budget depending on threat (leave room for upgrades)
        cap_ratio = 0.7 + (attack_analysis["defense_boost"] * 0.6)
        if num_hoarders >= 2:
            cap_ratio = min(0.9, cap_ratio + 0.1)  # Up to 90% if multiple hoarders
        armor_amount = min(armor_amount, int(budget * cap_ratio))

    # LEVEL 3+ MODE: Maintain HP + Armor >= 150, then defend/attack
    else:
        # After Level 3, always maintain minimum 150 total HP
        LEVEL3_TARGET_HP = 150
        current_total_hp = me.hp + me.armor
        needed_for_target = max(0, LEVEL3_TARGET_HP - current_total_hp)

    # LEVEL 3+ WITH INCOMING DAMAGE: More defensive focus with adaptive boost
    if not economy_mode and incoming_damage > 0:
        # Cover 100-120% of expected incoming (more if heavily attacked)
        coverage_ratio = 1.0 + (attack_analysis["defense_boost"] * 0.8)  # 1.0 to 1.2
        # Increase coverage if hoarders present
        coverage_ratio *= hoarder_multiplier

        # Base cap: 0.6 to 0.8 based on HP
        # Add defense boost for intensive attacks
        base_cap = 0.6 + (1.0 - hp_ratio) * 0.2  # 0.6 to 0.8
        cap_multiplier = min(0.95, base_cap + attack_analysis["defense_boost"])  # up to 0.95

        calculated_armor = int(incoming_damage * coverage_ratio)
        # Ensure we reach 150 total HP minimum
        armor_amount = max(needed_for_target, min(calculated_armor, int(budget * cap_multiplier)))
    elif not economy_mode and me.hp < 40:
        # Critical HP — go very defensive (70-80% of budget based on threat)
        cap_ratio = min(0.95, (0.7 + attack_analysis["defense_boost"]) * hoarder_multiplier)
        # Defend against max_threat instead of just avg_enemy_resources
        calculated_armor = int(max_threat * 0.5)
        armor_amount = max(needed_for_target, min(calculated_armor, int(budget * cap_ratio)))
    elif not economy_mode and me.hp < 60:
        # Low HP — invest significantly more (60-75% of budget based on threat)
        cap_ratio = min(0.85, (0.6 + attack_analysis["defense_boost"]) * hoarder_multiplier)
        calculated_armor = int(max_threat * 0.4)
        armor_amount = max(needed_for_target, min(calculated_armor, int(budget * cap_ratio)))
    elif not economy_mode:
        # Normal HP — higher defense (50-65% of budget based on threat)
        # If hoarders present, defend against potential burst
        cap_ratio = min(0.75, (0.5 + attack_analysis["defense_boost"]) * hoarder_multiplier)
        if num_hoarders > 0:
            # Prepare for burst attack
            calculated_armor = int(max_threat * 0.3)
        else:
            calculated_armor = int(avg_enemy_resources * 0.5)
        # Always ensure 150 total HP minimum at Level 3+
        armor_amount = max(needed_for_target, min(calculated_armor, int(budget * cap_ratio)))

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
    level3_defensive_mode: bool = False,
    duel_mode: bool = False,
    turn: int = 0,
    previous_attacks: list[CombatActionEntry] = None,
) -> int:
    if budget <= 0 or not enemies:
        return budget

    if previous_attacks is None:
        previous_attacks = []

    # ECONOMY MODE (Level < 3): NO ATTACKS - focus purely on upgrades
    # Zero attacks to maximize upgrade speed and reach Level 3 ASAP
    if economy_mode:
        return budget

    # Analyze enemy resource patterns
    enemy_resources = {}
    alive_enemies = []
    for e in enemies:
        if e.hp > 0:
            enemy_resources[e.playerId] = _estimate_enemy_resources(e, previous_attacks, turn)
            alive_enemies.append(e)

    # LEVEL 3+ STRATEGY: Accumulate resources for one-shot kill on weakest
    save_for_kill = False
    kill_target = None

    if me.level >= 3 and len(alive_enemies) > 0:
        # Find the weakest enemy (lowest effective HP)
        weakest = min(alive_enemies, key=lambda e: effective_hp(e))
        weakest_hp = effective_hp(weakest)

        # Calculate available attack budget (after mandatory armor for 150 HP)
        LEVEL3_TARGET_HP = 150
        current_total_hp = me.hp + me.armor
        needed_armor_for_survival = max(0, LEVEL3_TARGET_HP - current_total_hp)

        # Budget available for attacks (after ensuring survival)
        available_for_attack = budget - needed_armor_for_survival

        # Check if we can kill them this turn (with available attack budget)
        if weakest_hp <= available_for_attack and available_for_attack > 0:
            # We have enough - go for the kill!
            kill_target = weakest
        elif weakest_hp <= (available_for_attack + resource_gen(me.level)):
            # Can kill next turn if we save - accumulate resources
            save_for_kill = True
            kill_target = weakest

    # DUEL MODE: All-in attack with remaining budget
    if duel_mode:
        # In 1v1, use 100% of remaining budget - no saving
        budget_to_use = budget
        remaining_budget = 0

        # Maximum aggression - go for the kill
        hp_ratio = me.hp / 100.0
        aggression_factor = 1.0  # Max aggression in duel

    # LEVEL 3+ DEFENSIVE MODE: Save for one-shot, only attack if can kill
    elif level3_defensive_mode:
        # After armor (60%+), we have 40% budget left
        # Save it all UNLESS we can one-shot kill someone

        hp_ratio = me.hp / 100.0

        # Check if we can one-shot anyone with current budget
        can_oneshot = kill_target is not None and effective_hp(kill_target) <= budget

        if can_oneshot:
            # We can kill someone - use ALL remaining budget for it
            budget_to_use = budget
            remaining_budget = 0
            aggression_factor = 1.0  # Max aggression for kill
        elif save_for_kill:
            # Saving for next turn kill - minimal attacks (only retaliation if attacked)
            if len(attackers) > 0:
                # We were attacked - light retaliation with 20% budget
                budget_to_use = int(budget * 0.2)
                remaining_budget = budget - budget_to_use
                aggression_factor = 0.5  # Moderate
            else:
                # Not attacked - save everything
                budget_to_use = 0
                remaining_budget = budget
                aggression_factor = 0.0
        else:
            # Normal mode - can't one-shot anyone soon, save most resources
            # Only light attacks for pressure (20% of remaining)
            budget_to_use = int(budget * 0.2)
            remaining_budget = budget - budget_to_use
            aggression_factor = 0.4  # Low aggression

    else:
        # Economy mode or other - shouldn't happen but handle it
        budget_to_use = budget
        remaining_budget = 0

        hp_ratio = me.hp / 100.0
        aggression_factor = 0.3 + hp_ratio * 0.5

    # SAVE FOR KILL MODE: If accumulating for one-shot, minimal attacks
    if save_for_kill and kill_target:
        # Only attack if we can kill the target OR in retaliation
        # Otherwise save resources
        if kill_target.playerId not in attackers:
            # Not being attacked - save everything for next turn kill
            return remaining_budget

    # Score each enemy for targeting
    target_scores: list[tuple[EnemyTower, float]] = []

    for e in enemies:
        # Skip dead enemies - don't waste resources on eliminated players
        if e.hp <= 0:
            continue

        score = 0.0

        # KILL TARGET PRIORITY: Massive bonus if we can kill them
        if kill_target and e.playerId == kill_target.playerId:
            ehp = effective_hp(e)
            if ehp <= budget_to_use:
                score += 500  # HUGE priority - guaranteed kill

        # Get enemy resource analysis
        e_analysis = enemy_resources.get(e.playerId, {})
        is_turtle = e_analysis.get("is_turtle", False)
        is_hoarding = e_analysis.get("is_hoarding", False)

        # TURTLE DETECTION: Don't attack enemies with pure defense strategy
        if is_turtle and e.hp > 60:
            # They spend everything on armor - attacking them is wasteful
            score -= 200
            # Exception: if they're killable, still worth it
            ehp = effective_hp(e)
            if ehp <= budget_to_use:
                score += 250  # Override turtle penalty if killable

        # HOARDER DETECTION: Prioritize attacking hoarders to force them to spend
        if is_hoarding:
            score += 40  # Higher priority - they're dangerous

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
        if ehp <= budget_to_use:
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

    # Primary target budget: scale based on mode and HP
    if duel_mode:
        # Duel: go all-in on single target
        primary_budget_ratio = 0.9 + hp_ratio * 0.1  # 0.9 to 1.0
    elif level3_defensive_mode and can_oneshot:
        # Level 3+ defensive but can kill: focus fire
        primary_budget_ratio = 1.0  # 100% on killable target
    else:
        # Other modes: moderate focus
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
