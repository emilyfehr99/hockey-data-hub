-- Fact Table: Skater Game-by-Game Production & Micro-Tracking
CREATE TABLE IF NOT EXISTS fct_skater_game (
    game_id             INTEGER,              -- League official gameId
    player_uuid         UUID,                 -- Foreign key to dim_players(player_uuid)
    season_id           INTEGER,              -- e.g., 20242025
    game_date           DATE,
    team_tricode        VARCHAR(3),
    opponent_tricode    VARCHAR(3),
    is_home             BOOLEAN,
    situation           VARCHAR(10),          -- '5v5', 'all', 'pp', 'pk'
    
    -- Coverage flags & Sample Size
    has_pbp_events      BOOLEAN DEFAULT TRUE,
    has_possession_data BOOLEAN DEFAULT FALSE,
    has_transition_data BOOLEAN DEFAULT FALSE,
    has_micro_data      BOOLEAN DEFAULT FALSE,

    -- Ice Time
    toi_seconds         INTEGER,

    -- Boxscore Counts
    goals               INTEGER DEFAULT 0,
    assists             INTEGER DEFAULT 0,
    points              INTEGER DEFAULT 0,
    shots               INTEGER DEFAULT 0,
    hits                INTEGER,
    blocks              INTEGER,
    pim                 INTEGER DEFAULT 0,
    faceoff_pct         FLOAT,

    -- Sensor & Tracking Metrics
    edge_top_speed_mph  FLOAT,
    edge_bursts_over_20 INTEGER,
    edge_skating_dist_m FLOAT,

    -- 5v5 Possession & Danger Rates
    cf                  INTEGER,
    ca                  INTEGER,
    cf_pct              FLOAT,
    ff                  INTEGER,
    fa                  INTEGER,
    ff_pct              FLOAT,
    gf                  INTEGER,
    ga                  INTEGER,
    xgf                 FLOAT,
    xga                 FLOAT,
    xgf_pct             FLOAT,
    hdcf                INTEGER,
    hdca                INTEGER,
    hdcf_pct            FLOAT,
    pdo                 FLOAT,
    ozs_pct             FLOAT,

    -- Transition & Playmaking Microstats
    controlled_entries          INTEGER,
    carry_in_pct                FLOAT,
    entry_denials               INTEGER,
    entry_denial_pct            FLOAT,
    exits_with_possession       INTEGER,
    primary_shot_assists        INTEGER,
    cross_slot_passes           INTEGER,
    forecheck_retrievals        INTEGER,
    microstat_game_score        FLOAT,

    -- Event & Puck Battle Metrics
    scoring_chances             INTEGER,
    slot_passes                 INTEGER,
    dz_retrievals               INTEGER,
    turnovers                   INTEGER,
    dz_turnovers                INTEGER,
    battles_won                 INTEGER,
    battles_total               INTEGER,
    battle_win_pct              FLOAT,

    PRIMARY KEY (game_id, player_uuid, situation)
);

CREATE INDEX IF NOT EXISTS idx_fct_skater_player ON fct_skater_game(player_uuid);
CREATE INDEX IF NOT EXISTS idx_fct_skater_season ON fct_skater_game(season_id);
