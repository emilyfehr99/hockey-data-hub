-- Fact Table: Play-by-Play Events with Rink Coordinates
CREATE TABLE IF NOT EXISTS fct_event_pbp (
    match_id            INTEGER,
    event_id            INTEGER,
    period              INTEGER,
    start_sec           INTEGER,
    end_sec             INTEGER,
    duration_sec        INTEGER,
    pos_x               FLOAT,
    pos_y               FLOAT,
    player_uuid         UUID,
    player_name         VARCHAR(100),
    team_name           VARCHAR(100),
    action_type         VARCHAR(100),
    action_category     VARCHAR(50),      -- 'entry', 'exit', 'shot', 'pass', 'battle', 'faceoff'

    PRIMARY KEY (match_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_event_pbp_match ON fct_event_pbp(match_id);
CREATE INDEX IF NOT EXISTS idx_event_pbp_player ON fct_event_pbp(player_uuid);
CREATE INDEX IF NOT EXISTS idx_event_pbp_action ON fct_event_pbp(action_type);
