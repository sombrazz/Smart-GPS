from app.simulation.engine import SimulationEngine


def test_generate_synthetic_dataset_rows():
    engine = SimulationEngine(seed=123)
    rows = engine.generate_synthetic_scenarios(40)
    assert len(rows) >= 40
    required_fields = {
        "timestamp",
        "team_id",
        "vehicle_id",
        "distance_to_team_m",
        "base_eta_s",
        "best_vehicle_label",
    }
    assert required_fields.issubset(rows[0].keys())
