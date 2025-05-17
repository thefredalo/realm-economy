# =========================================================
# prespur_economy_with_reasons.py
# Ilha Prespur realm-economy simulator with probabilistic boom/slump reasons
# =========================================================
import random
import logging
from dataclasses import dataclass
from typing import Dict, Optional, List

# ---------- Constants & Configuration ----------
DIE_LADDER = ["d0", "d2", "d4", "d6", "d8", "d10", "d12"]
GP_PER_EXPORT_STEP = 5  # this changes how much exports are worth per dice and changes flat rev!
LOYALTY_GROWTH_FACTOR = 0.05
TARIFF_RATE = 1  # % tariff on all imports

BOOM_THRESHOLD = 7
SLUMP_THRESHOLD = 5
TREND_BOOM_TRIGGER = 0.035
TREND_SLUMP_TRIGGER = -0.035

# Random swing ±5%
R_RANGE = 0.1
# DM bias: +0.02 boom, -0.03 slump
ECON_BIAS = 0

# Narrative reasons for booms and slumps
REASONS_BOOM = [
    "surge in overseas demand",
    "new trade treaty signed with a wealthy ally",
    "bountiful harvest season",
    "merchant caravan discovered rare ore deposits",
    "winds favour rapid shipping",
    "a local weaver wins a foreign festival prize, doubling orders for her tapestries.",
    "explorers uncover a new inland salt spring; salt exports tick up overnight.",
    "visiting nobles host a gala and spend lavishly in town.",
    "a famous bard by the name of William Shake-Spear performs and draws crowds and boosts tavern takings (and dock fees).",
    "the famous craft guild member Henry Fjord invents a faster production method; carts are suddenly cheaper.",
    "the religious fervour of the island blessing draws pilgrims to the marketplace.",
    "King Edward 'Shonglanks' remade their coinage system, revitalising their currency's worth. Next on the agenda: Kick out the Jews!",
    "cartographers chart a shortcut across the reef, shaving days off voyages.",
    "a traveling university campus sets up near the keep, hiring local labor.",
    "farmers plant by moonlight under a druid's guidance, yielding a bumper crop.",
    "meelon musk attempted to send a rock into space using a peasant railgun. this excited the markets, and they threw their hearts out to him",
    "banks are handing out frivolous loans. this surely can't go wrong!"
]
REASONS_SLUMP = [
    "poor harvest season",
    "pirate raids disrupted merchant routes",
    "outbreak of livestock disease",
    "regional conflict cut off key supply lines",
    "storms damaged several shipments, taking Laurence of Ludlow with them",
    "the main grain mills wheel cracks, halving flour output for weeks.",
    "GWR is on strike. Again.",
    "a dictator of a far-off kingdom named Tronald Muck has imposed far too many tariffs, making the global economy worse off. At least he got a cool new airship, right?",
    "the weavers' guild protests a new tax by refusing to sell cloth to city officials.",
    "a small raiding party waylays a timber convoy on the forest road.",
    "a sudden plague of rats tears through docks, spoiling stored grain and salt.",
    "a scandal over tainted meat from Kara-Tur crashes that market overnight.",
    "a banking scandal freezes merchant credit lines",
    "A major merchant guild in Cormyr boycott the docks in protest of new tariffs. the new king claims they're communists.",
    "don't ask me. i just work here.",
    "coronation street was on, so everyone decided to take the day off.",
    "Just Stop Peat protesters tied themselves to a trade ship's mast and disrupted its schedule."
]

NEIGHBOURS = {
    "Cormyr": {"pop": 4, "rel": 1, "dist": 5,
               "scarcity": {"fish": 0.5, "timber": 1, "salt": 1}},
    "Sembia": {"pop": 6, "rel": 0, "dist": 3,
               "scarcity": {"fish": 0, "timber": 1, "salt": 0}},
    "Pirate Isles": {"pop": 1, "rel": -1, "dist": 1,
                     "scarcity": {"fish": 0, "timber": 2, "salt": 0}}
}

# Setup Logging
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(levelname)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Data Class
@dataclass
class EconomyState:
    trade_die: str
    agri_die: str
    exports: Dict[str, str]
    revenue: Dict[str, int]
    export_quantities: Dict[str, int]  # Renamed from export_rolls and using keys from exports
    costs: Dict[str, int]
    import_penalties: int
    upkeep: int
    loyalty_tier: int
    treasury: int
    total_import_value: int = 0  # To track imports for tariffs

    def validate(self):
        for die in [self.trade_die, self.agri_die] + list(self.exports.values()):
            if die not in DIE_LADDER:
                raise ValueError(f"Invalid die code: {die}")
        for val in list(self.revenue.values()) + list(self.costs.values()):
            if not isinstance(val, int) or val < 0:
                raise ValueError("Revenue/cost values must be non-negative ints.")
        if self.import_penalties < 0 or self.upkeep < 0:
            raise ValueError("Import penalties and upkeep must be non-negative.")
        if not (0 <= self.loyalty_tier <= 5):
            raise ValueError("Loyalty tier must be between 0 and 5.")
        if self.treasury < 0:
            raise ValueError("Treasury cannot be negative.")
        if self.total_import_value < 0:
            raise ValueError("Total import value cannot be negative.")

# Helper Functions

def roll_die(code: str) -> int:
    return random.randint(1, int(code[1:]))

def die_size(code: str) -> int:
    return int(code[1:])

def avg_export_size(exports: Dict[str, str]) -> float:
    if not exports:
        return 0.0
    return sum(die_size(d) for d in exports.values()) / len(exports)

def growth_modifier(exports: Dict[str, str]) -> float:
    avg_ei = round(avg_export_size(exports))
    return max(-0.20, min(0.20, (avg_ei - 6) / 20.0))

def random_variance() -> float:
    return random.uniform(-R_RANGE, R_RANGE) + ECON_BIAS

def step_die(code: str, up: bool = True) -> str:
    idx = DIE_LADDER.index(code)
    idx = max(0, min(idx + (1 if up else -1), len(DIE_LADDER) - 1))
    return DIE_LADDER[idx]

def demand_score(pop: int, scar: int, rel: int, dist: int) -> int:
    return max(0, (pop + scar + rel) - dist)

def foreign_sales(exports: Dict[str, str]) -> int:
    gp = 0
    for data in NEIGHBOURS.values():
        for comm, die in exports.items():
            scar = data['scarcity'].get(comm, 0)
            score = demand_score(data['pop'], scar, data['rel'], data['dist'])
            if score > 0:
                gp += score * die_size(die) * GP_PER_EXPORT_STEP
    return gp

# Simulator
class EconomySimulator:
    def __init__(self, seed: Optional[int] = None):
        if seed is not None:
            random.seed(seed)

    def simulate_month(self, state: EconomyState, verbose: bool = True) -> EconomyState:
        state.validate()
        # Roll core dice
        t_roll = roll_die(state.trade_die)
        a_roll = roll_die(state.agri_die)
        trade_gp = 25 * t_roll
        agri_gp = 10 * a_roll

        # Calculate export revenue based on quantities and GP_PER_EXPORT_STEP
        exp_gp = sum(state.export_quantities.get(item, 0) * GP_PER_EXPORT_STEP for item in state.exports)
        foreign_gp = foreign_sales(state.exports)
        state.revenue['foreign_sales'] = foreign_gp

        # Calculate potential tariff (assuming a fixed import value for simplicity here)
        # In a more complex model, this would be based on actual imported goods and their value.
        # For this example, we'll use a fixed percentage of the total revenue.
        potential_tariff = round((trade_gp + agri_gp + sum(state.revenue.values()) + exp_gp + foreign_gp) * (TARIFF_RATE / 100))
        state.revenue['trade_tariff'] = potential_tariff
        outflows = sum(state.costs.values()) + state.import_penalties + state.upkeep + potential_tariff # Tariffs are an outflow

        # Totals & profit
        flat_rev = state.revenue.get('other_income', 0) + state.revenue.get('luxury_tax', 0) + state.revenue.get('gate_fees', 0)
        raw = trade_gp + agri_gp + flat_rev + exp_gp + foreign_gp - (sum(state.costs.values()) + state.import_penalties + state.upkeep)
        trend = growth_modifier(state.exports) + random_variance()
        profit = round(raw * (1 + LOYALTY_GROWTH_FACTOR * state.loyalty_tier + trend))
        state.treasury += profit

        # Determine boom/slump probabilistically
        boom = trend >= TREND_BOOM_TRIGGER
        slump = trend <= TREND_SLUMP_TRIGGER
        # Fall back to hard thresholds if rarely triggered
        avg_ei = round(avg_export_size(state.exports))
        if not boom and avg_ei >= BOOM_THRESHOLD:
            boom = True
        if not slump and avg_ei <= SLUMP_THRESHOLD:
            slump = True

        reason = None
        if boom:
            if state.exports:
                worst = min(state.exports, key=lambda k: die_size(state.exports[k]))
                state.exports[worst] = step_die(state.exports[worst], up=True)
            state.trade_die = step_die(state.trade_die, up=True)
            reason = random.choice(REASONS_BOOM)
        elif slump:
            if state.exports:
                best = max(state.exports, key=lambda k: die_size(state.exports[k]))
                state.exports[best] = step_die(state.exports[best], up=False)
            state.trade_die = step_die(state.trade_die, up=False)
            reason = random.choice(REASONS_SLUMP)

        # Verbose output
        if verbose:
            print("-- Inflows --")
            print(f"  Trade     : +{trade_gp} gp (25×{t_roll})")
            print(f"  Agri      : +{agri_gp} gp (10×{a_roll})")
            print(f"  Flat Rev  : +{flat_rev} gp")
            if exp_gp:
                print(f"  Exports   : +{exp_gp} gp")
            print(f"  Foreign   : +{foreign_gp} gp")
            print("-- Outflows --")
            for name, cost in state.costs.items():
                print(f"  {name:12}: -{cost} gp")
            print(f"  Imports   : -{state.import_penalties} gp")
            print(f"  Upkeep    : -{state.upkeep} gp")
            print(f"  Tariffs   : -{potential_tariff} gp")
            print(f"Raw Income  : {raw:+} gp")
            print(f"Trend Score : {trend:.2f} (growth+rand)")
            print(f"Net Profit  : {profit:+} gp   -> Treasury {state.treasury} gp")
            if boom or slump:
                label = 'Boom reason' if boom else 'Slump reason'
                print(f"{label:14}: {reason.capitalize()}")
            else:
                print("No boom or slump this month.")

        return state

if __name__ == "__main__":
    initial = EconomyState(
        trade_die="d6",
        agri_die="d6",
        exports={"fish": "d4", "timber": "d4", "salt": "d0", "olives": "d2", "wine": "d2", "grain": "d8"},
        revenue={"trade_tariff": 0, "luxury_tax": 5, "gate_fees": 0, "other_income": 300},
        export_quantities={"fish": 2, "timber": 2, "salt": 0, "olives": 1, "wine": 1, "grain": 3},
        costs={"festival_grant": 75, "road_levy": 0, "bounties": 5},
        import_penalties=300,
        upkeep=400,
        loyalty_tier=0,
        treasury=1000,
        total_import_value=0  # Initialize import value
    )

    sim = EconomySimulator()
    result = sim.simulate_month(initial, verbose=True)

    # total exports
    exp_gp = sum(result.export_quantities.get(item, 0) * GP_PER_EXPORT_STEP for item in result.exports)
    foreign_gp = result.revenue.get('foreign_sales', 0)
    total_export_gp = exp_gp + foreign_gp
    print(f"\nTotal exported this month: {total_export_gp} gp "
          f"({exp_gp} domestic + {foreign_gp} foreign)")

    # Show actual tariff revenue
    actual_tariff = result.revenue.get('trade_tariff', 0)
    print(f"Tariffs collected this month: {actual_tariff} gp")