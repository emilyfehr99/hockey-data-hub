-- Fact Table: Goalie Game-by-Game Multi-Layer Performance
CREATE TABLE IF NOT EXISTS fct_goalie_game (
    game_id             INTEGER,
    player_uuid         UUID,
    season_id           INTEGER,
    game_date           DATE,
    team_tricode        VARCHAR(3),
    opponent_tricode    VARCHAR(3),
    decision            VARCHAR(1),           -- 'W', 'L', 'O'
    toi_seconds         INTEGER,

    -- Traditional Boxscore
    shots_against       INTEGER,
    saves               INTEGER,
    goals_against       INTEGER,
    save_pct            FLOAT,
    shutout             BOOLEAN DEFAULT FALSE,

    -- Danger Splits & Advanced Metrics
    has_danger_data     BOOLEAN DEFAULT FALSE,
    hd_shots_against    INTEGER,
    hd_saves            INTEGER,
    hd_goals_against    INTEGER,
    hd_save_pct         FLOAT,
    md_save_pct         FLOAT,
    ld_save_pct         FLOAT,
    xg_against          FLOAT,
    gsaa                FLOAT,                -- Goals Saved Above Average
    gsax                FLOAT,                -- Goals Saved Above Expected (xGA - GA)

    -- Tracking Context
    has_event_tracking  BOOLEAN DEFAULT FALSE,
    screen_goals_against INTEGER,
    rebound_control_pct FLOAT,

    PRIMARY KEY (game_id, player_uuid)
);

CREATE INDEX IF NOT EXISTS idx_fct_goalie_player ON fct_goalie_game(player_uuid);
CREATE INDEX IF NOT EXISTS idx_fct_goalie_season ON fct_goalie_game(season_id);
