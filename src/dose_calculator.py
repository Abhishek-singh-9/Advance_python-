def allowed_time_hours(level_dba, profile="niosh"):
    # TEMPORARY stub
    if profile == "niosh":
        return 8 / 2 ** ((level_dba - 85) / 3)
    return (40 / 7) / 2 ** ((level_dba - 80) / 3)  # stub guess for WHO


def dose_percent(periods, profile="niosh"):
    return 100 * sum(h / allowed_time_hours(l, profile) for l, h in periods)