-- Canonical Player Dimension Table
CREATE TABLE IF NOT EXISTS dim_players (
    player_uuid         UUID PRIMARY KEY,
    nhl_player_id       INTEGER UNIQUE,
    tracking_player_id  INTEGER UNIQUE,
    player_slug         VARCHAR UNIQUE,
    first_name          VARCHAR,
    last_name           VARCHAR,
    full_name           VARCHAR,
    birth_date          DATE,
    draft_year          INTEGER,
    draft_round         INTEGER,
    draft_overall       INTEGER,
    draft_team          VARCHAR(3),
    primary_position    VARCHAR(2),      -- 'C', 'L', 'R', 'D', 'G'
    shoots_catches      VARCHAR(1),      -- 'L', 'R'
    height_inches       INTEGER,
    weight_lbs          INTEGER,
    birth_country       VARCHAR(3),
    birth_city          VARCHAR(100),
    birth_state_province VARCHAR(100),
    current_team        VARCHAR(3),
    headshot_url        VARCHAR(255),
    hero_image_url      VARCHAR(255),
    career_gp           INTEGER,
    career_goals        INTEGER,
    career_assists      INTEGER,
    career_points       INTEGER,
    is_active_nhl       BOOLEAN DEFAULT FALSE,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dim_players_nhl ON dim_players(nhl_player_id);
CREATE INDEX IF NOT EXISTS idx_dim_players_tracking ON dim_players(tracking_player_id);
CREATE INDEX IF NOT EXISTS idx_dim_players_slug ON dim_players(player_slug);
