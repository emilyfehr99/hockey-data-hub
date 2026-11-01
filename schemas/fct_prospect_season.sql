-- Fact Table: Junior, College & International Prospects
CREATE TABLE IF NOT EXISTS fct_prospect_season (
    player_uuid             UUID,
    season_id               INTEGER,
    league_code             VARCHAR(10),
    team_name               VARCHAR(60),
    age_sept_15             FLOAT,
    is_draft_eligible       BOOLEAN,
    
    -- Official Production
    games_played            INTEGER,
    goals                   INTEGER,
    assists                 INTEGER,
    points                  INTEGER,
    points_per_game         FLOAT,
    shots_on_goal           INTEGER,
    pim                     INTEGER,

    -- Prospect Microstats
    has_microstats          BOOLEAN DEFAULT FALSE,
    scoring_chances         INTEGER,
    controlled_entries      INTEGER,
    carry_in_pct            FLOAT,
    controlled_exits        INTEGER,
    slot_passes             INTEGER,
    battles_total           INTEGER,
    battle_win_pct          FLOAT,

    PRIMARY KEY (player_uuid, season_id, league_code, team_name)
);

CREATE INDEX IF NOT EXISTS idx_fct_prospect_player ON fct_prospect_season(player_uuid);
CREATE INDEX IF NOT EXISTS idx_fct_prospect_league ON fct_prospect_season(league_code);
