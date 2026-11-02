-- Fact Table: High-Frequency Goal Tracking Sprites & Trajectories (10 Hz Sensor Stream)
CREATE TABLE IF NOT EXISTS fct_goal_sprites (
    game_id             INTEGER,
    event_id            INTEGER,
    season_id           INTEGER,
    period              INTEGER,
    frame_index         INTEGER,              -- 0 to 119 (10 frames per second over ~12 sec)
    timestamp           BIGINT,
    entity_type         VARCHAR(10),          -- 'puck', 'skater', 'goalie'
    player_id           INTEGER,              -- NULL for puck
    player_uuid         UUID,
    sweater_number      INTEGER,
    team_tricode        VARCHAR(3),
    is_scoring_team     BOOLEAN,
    coord_x             FLOAT,                -- High-resolution tracking coordinate
    coord_y             FLOAT,

    PRIMARY KEY (game_id, event_id, frame_index, entity_type, player_id)
);

CREATE INDEX IF NOT EXISTS idx_sprites_game_event ON fct_goal_sprites(game_id, event_id);
CREATE INDEX IF NOT EXISTS idx_sprites_player ON fct_goal_sprites(player_uuid);
