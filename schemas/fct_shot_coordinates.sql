-- Fact Table: NHL Shot Coordinates and Event Micro-Attributes
CREATE TABLE IF NOT EXISTS fct_shot_coordinates (
    game_id             INTEGER,
    shot_index          INTEGER,
    period              INTEGER,
    team_id             INTEGER,
    shooter_uuid        UUID,
    goalie_uuid         UUID,
    shooter_nhl_id      INTEGER,
    goalie_nhl_id       INTEGER,
    coord_x             FLOAT,
    coord_y             FLOAT,
    shot_type           VARCHAR(30),       -- 'wrist', 'slap', 'snap', 'backhand', 'tip-in', 'wrap-around'
    is_goal             BOOLEAN,
    is_rebound          BOOLEAN,
    is_rush             BOOLEAN,
    score_state         VARCHAR(10),

    PRIMARY KEY (game_id, shot_index)
);

CREATE INDEX IF NOT EXISTS idx_shots_game ON fct_shot_coordinates(game_id);
CREATE INDEX IF NOT EXISTS idx_shots_shooter ON fct_shot_coordinates(shooter_uuid);
CREATE INDEX IF NOT EXISTS idx_shots_goalie ON fct_shot_coordinates(goalie_uuid);
