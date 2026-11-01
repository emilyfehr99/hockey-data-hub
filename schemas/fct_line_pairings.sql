-- Fact Table: Line Combinations and Defensive Pairings
CREATE TABLE IF NOT EXISTS fct_line_pairings (
    season_id           INTEGER,              -- e.g. 20242025
    game_id             INTEGER,              -- Optional if aggregated across season
    team_tricode        VARCHAR(3),
    unit_type           VARCHAR(10),          -- 'forward_line', 'defense_pair'
    line_name           VARCHAR(150),         -- e.g., 'Connor McDavid - Zach Hyman - Ryan Nugent-Hopkins'
    player_1_uuid       UUID,
    player_2_uuid       UUID,
    player_3_uuid       UUID,                 -- NULL for defense pairs
    situation           VARCHAR(10),          -- '5v5', 'all', 'pp', 'pk'
    
    -- Ice Time
    games_played        INTEGER DEFAULT 1,
    toi_seconds         INTEGER,
    
    -- On-Ice Shot & Goal Metrics
    cf                  INTEGER,
    ca                  INTEGER,
    cf_pct              FLOAT,
    ff                  INTEGER,
    fa                  INTEGER,
    ff_pct              FLOAT,
    sf                  INTEGER,
    sa                  INTEGER,
    gf                  INTEGER,
    ga                  INTEGER,
    xgf                 FLOAT,
    xga                 FLOAT,
    xgf_pct             FLOAT,
    hdcf                INTEGER,
    hdca                INTEGER,
    hdcf_pct            FLOAT,
    
    -- Shooting / Save Percentages & PDO
    on_ice_sh_pct       FLOAT,
    on_ice_sv_pct       FLOAT,
    pdo                 FLOAT,
    ozs_pct             FLOAT,

    PRIMARY KEY (season_id, team_tricode, unit_type, line_name, situation)
);

CREATE INDEX IF NOT EXISTS idx_fct_lines_team ON fct_line_pairings(team_tricode);
CREATE INDEX IF NOT EXISTS idx_fct_lines_season ON fct_line_pairings(season_id);
