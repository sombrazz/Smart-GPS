from app.simulation.engine import SimulationEngine


def test_rule_based_vehicle_selection_returns_available_vehicle():
    engine = SimulationEngine(seed=9)
    team = engine.teams["T-01"]
    team.active_request = True
    selected = engine._choose_vehicle_for_team(team)
    assert selected is not None
    assert selected["vehicle_id"] in engine.vehicles
    assert engine.vehicles[selected["vehicle_id"]].available


def test_configure_scenario_changes_entity_counts():
    engine = SimulationEngine(seed=11)
    state = engine.configure_scenario(vehicle_count=9, team_count=13)
    assert state["meta"]["scenario"]["vehicle_count"] == 9
    assert state["meta"]["scenario"]["team_count"] == 13
    assert len(engine.vehicles) == 9
    assert len(engine.teams) == 13


def test_compare_strategies_returns_summary():
    engine = SimulationEngine(seed=11)
    comparison = engine.compare_strategies(steps=5)
    assert comparison["steps"] == 5
    assert "rule" in comparison
    assert "ml" in comparison
    assert "delta" in comparison
