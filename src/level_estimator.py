def estimate_level(volume_step, max_step, profile_id, content="typical"):
    # TEMPORARY stub: fake level from volume position
    level = 60 + 25 * (volume_step / max_step)
    return {"level_dba": round(level, 1), "margin_db": 5,
            "method": "lookup", "label": "simulated"}