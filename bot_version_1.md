# Bot Version 1 - "Aggressive Retaliator"

**Date:** 2026-02-11
**Status:** Current Production Version
**Strategy:** Rush upgrades early, focus fire, aggressive retaliation

---

## Overview

This is the initial bot strategy for Kingdom Wars. The core philosophy emphasizes:
1. Rush upgrades early — resource advantage compounds hard
2. Focus fire — eliminating a player is worth more than spreading damage
3. Diplomacy — gang up on the strongest threat
4. Armor is cheap insurance when being targeted
5. Late-game: pure aggression before fatigue kills everyone

---

## Implementation Details

### Constants
- `MAX_LEVEL = 5`
- `FATIGUE_START = 25`
- `GAME_HORIZON = 40` (approximate max game length)

### Core Functions

#### Resource Calculations
```python
upgrade_cost(level) = ceil(50 × 1.75^(level-1))
resource_gen(level) = ceil(20 × 1.5^(level-1))
```

#### Threat Scoring
```python
threat_score = resource_gen(level) × 2.0 + hp × 0.3 + armor × 0.2
if attacked_us:
    threat_score += 40 + troop_count × 0.5
```

---

## Strategy Breakdown

### 1. Negotiation Phase

**Logic:** Target the biggest economic threat

```python
def decide_negotiation(req):
    # Score all enemies by threat level
    # Find biggest threat (highest resource generation + combat power)
    # Propose alliance with EVERYONE except biggest threat
    # Ask all allies to attack biggest threat together
```

**Strengths:**
- Simple and consistent
- Coordinates attacks on strongest player
- Forms multiple alliances simultaneously

**Weaknesses:**
- Predictable (always targets strongest)
- Doesn't consider who attacked us
- May anger the strongest player early

---

### 2. Combat Phase - Upgrades

**Logic:** Upgrade if it pays back within 60% of remaining game

```python
def _maybe_upgrade(me, turn, budget):
    if level >= MAX_LEVEL:
        return budget

    cost = upgrade_cost(level)
    payback_turns = cost / extra_income_per_turn
    turns_left = GAME_HORIZON - turn

    if payback_turns < turns_left × 0.6 AND turn <= 20:
        upgrade()
        budget -= cost
```

**Upgrade Timeline:**
- Level 1→2: Round 2-3 (cost 50)
- Level 2→3: Round 6-8 (cost 88)
- Level 3→4: Round 12-15 (cost 153)
- Stops upgrading after round 20

**Strengths:**
- Prioritizes economy early
- Good ROI calculation

**Weaknesses:**
- Hard cutoff at turn 20 is arbitrary
- Doesn't consider HP state (upgrades even when dying)
- Should extend to round 23-24 before fatigue

---

### 3. Combat Phase - Armor

**Logic:** Minimal armor, scales with incoming damage

```python
def _maybe_armor(me, turn, budget, attackers, enemies):
    incoming_damage = sum(attackers.values())

    if incoming_damage > 0:
        # Cover 60% of expected incoming
        armor = min(int(incoming_damage × 0.6), budget // 3)
    elif turn <= 3:
        # Minimal early armor
        armor = min(5, budget // 4)
    elif hp < 50:
        # Low HP — invest more
        armor = min(int(avg_enemy_resources × 0.5), budget // 3)
    else:
        # Light defensive buffer
        armor = min(int(avg_enemy_resources × 0.25), budget // 5, 15)
```

**Armor Allocation:**
- Early game (turn 1-3): 5 armor max
- Under attack: 60% of incoming, capped at budget//3
- Low HP (<50): capped at budget//3
- Normal: 25% of avg enemy resources

**Strengths:**
- Adaptive to incoming damage
- Cheap early game (saves for upgrades)

**Weaknesses:**
- **CRITICAL FLAW:** Only covers 60% of damage
- **CRITICAL FLAW:** budget//3 cap means often inadequate
- Even at HP=40, only spends 33% on armor
- Early 5 armor is too low (should be 10-15)

**Example Problem:**
```
Round 10: HP=60, Resources=60, Incoming=50
Armor: min(30, 20) = 20
Damage taken: 50 - 20 = 30
New HP: 30 (critical!)
```

---

### 4. Combat Phase - Attacks

**Logic:** Focus fire with heavy retaliation bias

```python
def _decide_attacks(enemies, budget, attackers, allies, agreed_targets):
    for each enemy:
        score = 0

        # Retaliation — STRONG incentive
        if enemy attacked us:
            score += 100 + their_troops × 1.5

        # Coordinated attack bonus
        if enemy in agreed_targets:
            score += 70

        # Don't attack allies (unless they hit us)
        if enemy in allies AND not in attackers:
            score -= 300

        # Prefer killable targets
        if can_kill_this_turn:
            score += 80

        # Prefer weaker targets
        score += 150 / (effective_hp + 1)

        # Higher level = more dangerous
        score += level × 8

    # Dump 75% budget on primary target
    primary_spend = min(budget, max(ehp, budget × 0.75))
```

**Attack Priority:**
1. Retaliation (+100 base + troops×1.5)
2. Coordinated targets (+70)
3. Killable targets (+80)
4. Weak targets (+150/hp)
5. High level targets (+level×8)

**Spending:**
- Primary target: 75% of remaining budget
- Secondary targets: remaining budget

**Strengths:**
- Strong focus fire (good for eliminations)
- Respects alliances
- Prioritizes finishes

**Weaknesses:**
- **CRITICAL FLAW:** Retaliation too strong (score +100)
- Revenge even when HP < 50 (suicidal)
- Dumps 75% budget even when should defend
- No HP-awareness in attack decisions

**Example Problem:**
```
HP=40, Budget=50, Attacked by player X with 30 troops
Score for X: 100 + 30×1.5 = 145 (highest!)
Spend on X: 50 × 0.75 = 37
Armor: 13 (from earlier phase)
Result: Revenge attack but die next round
```

---

## Critical Flaws Analysis

### Flaw #1: Insufficient Armor (CRITICAL)

**Problem:** Bot rarely builds adequate armor

**Numbers:**
```
Scenario: Incoming 50 damage, Budget 60
Current: armor = min(30, 20) = 20 → Take 30 damage
Needed: armor = 40-50 → Take 0-10 damage
```

**Impact:** Dies 5-8 rounds too early

---

### Flaw #2: Suicidal Retaliation (CRITICAL)

**Problem:** Revenge even when dying

**Numbers:**
```
HP=30, Attacked by 40 troops
Retaliation score: 100 + 60 = 160
Spends: 75% of budget on revenge
Should: Spend 70% on armor, 30% on defense
```

**Impact:** Eliminated trying to revenge

---

### Flaw #3: No HP Awareness (HIGH)

**Problem:** Strategy doesn't adapt to HP

**Example:**
```
HP=100, Budget=60 → armor=15, attack=45 ✓ OK
HP=40, Budget=60 → armor=15, attack=45 ✗ WRONG!
```

**Needed:** Scale armor/attack ratio based on HP

---

### Flaw #4: Early Upgrade Cutoff (MEDIUM)

**Problem:** Stops upgrading at turn 20, but fatigue is turn 25

**Lost value:**
```
Turn 21: Could upgrade to level 5 (268 cost)
Rounds 21-24: Would generate +33/turn
Total lost: 132 resources
```

---

### Flaw #5: Minimal Early Armor (LOW)

**Problem:** Only 5 armor rounds 1-3

**Risk:**
```
Round 2: Some aggressive bot attacks with 20 troops
Our armor: 5
Damage taken: 15
HP: 85 (early disadvantage)
```

**Should:** 10-15 armor early game

---

## Performance Metrics (Estimated)

### Typical Game Trajectory
```
Round 5:  HP=85,  Level=2, Resources=30
Round 10: HP=60,  Level=3, Resources=45
Round 15: HP=35,  Level=3, Resources=45
Round 18: ELIMINATED
```

### Expected Placement
- Win rate: ~10%
- Avg placement: #3-4 out of 4
- Avg survival: 16-19 rounds
- Cause of death: Insufficient armor → HP drain → eliminated

---

## Strengths

1. ✅ **Strong early economy** - Prioritizes upgrades well
2. ✅ **Good focus fire** - Eliminates targets effectively
3. ✅ **Simple diplomacy** - Forms alliances consistently
4. ✅ **Finish priority** - Recognizes value of eliminations

---

## Weaknesses

1. ❌ **Critical armor shortage** - Doesn't build enough defense
2. ❌ **Suicidal retaliation** - Revenge over survival
3. ❌ **No HP adaptation** - Same strategy at 100 HP and 30 HP
4. ❌ **Predictable diplomacy** - Always targets strongest
5. ❌ **Early upgrade cutoff** - Stops at turn 20 (should be 23-24)
6. ❌ **Poor late-game prep** - Doesn't prepare for fatigue

---

## Key Metrics

### Resource Allocation (Average)
```
Upgrades: 40%
Armor:    20%
Attacks:  40%
```

### Armor Coverage
```
Under attack: 60% of incoming (SHOULD BE: 100%)
Normal:       25-30% of budget (SHOULD BE: 35-40%)
Low HP:       33% of budget (SHOULD BE: 50-70%)
```

### Attack Aggressiveness
```
Primary target: 75% of attack budget
No HP scaling: Same at HP=100 and HP=30
```

---

## Game Theory Issues

### Issue #1: Predictable Target Selection
- Always gangs up on strongest
- Strongest player knows they're targeted
- Might pre-emptively attack us

### Issue #2: Weakest Link Vulnerability
- If we become weakest (HP < 40)
- All 3 opponents will finish us
- Current strategy doesn't prevent this

### Issue #3: No Endgame Strategy
- Same tactics round 5 and round 25
- Doesn't prepare for fatigue damage
- No "final 2" strategy

---

## Mathematical Analysis

### Armor Efficiency
```
Defense: 1 resource = 1 armor = blocks 1 damage (100% efficiency)
Attack: 1 resource = 1 damage (but blocked by armor)
```

**Current bot undervalues defense by ~40%**

### Damage Accumulation
```
With current armor (60% coverage):
Round 10-15: Take 40% of damage each turn
If attacked by 40/turn: Take 16 damage/turn
Over 5 rounds: 80 HP lost
Result: Dead by round 15
```

### Upgrade ROI
```
Level 1→2: 5 turns payback (excellent)
Level 2→3: 5.9 turns (good)
Level 3→4: 6.7 turns (acceptable)
Level 4→5: 8.1 turns (marginal if done late)
```

**Turn 20 cutoff wastes 5 good upgrade rounds (20-24)**

---

## Comparison to Optimal Strategy

| Aspect | Current (v1) | Optimal |
|--------|-------------|---------|
| Armor % | 20-30% | 35-50% |
| Attack % | 40-50% | 30-40% |
| Upgrade cutoff | Turn 20 | Turn 23-24 |
| HP awareness | None | Full scaling |
| Retaliation | +100 base | +50 base, HP-scaled |
| Survival (avg) | Round 17 | Round 25+ |

---

## Code Locations

### Key Files
- `src/strategy.py` - Main strategy logic
- `src/models.py` - Data models
- `src/main.py` - FastAPI endpoints

### Critical Functions
- `decide_negotiation()` - Line 77-116
- `decide_combat()` - Line 123-149
- `_maybe_upgrade()` - Line 156-179
- `_maybe_armor()` - Line 182-218 (NEEDS FIX)
- `_decide_attacks()` - Line 221-297 (NEEDS FIX)

---

## Conclusion

**Bot Version 1** is an **aggressive, economy-focused strategy** that:
- ✅ Builds economy well early game
- ✅ Eliminates targets effectively
- ❌ **Dies too early from insufficient defense**
- ❌ **Suicidal retaliation behavior**

**Primary failure mode:** HP drain from inadequate armor → weakest link → eliminated rounds 15-19

**Next version should:** Shift 15-20% of attack budget to armor, add HP-awareness to all decisions, extend upgrade window to turn 23-24.

---

## Version History

- **v1.0** (2026-02-11) - Initial aggressive strategy
- **v2.0** (Planned) - Defensive rebalance

---

*End of Bot Version 1 Documentation*
