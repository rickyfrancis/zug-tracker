-- Runs once, when the postgres data volume is first initialised.
-- PostGIS backs the geographic station coordinates imported in Phase 2.
CREATE EXTENSION IF NOT EXISTS postgis;
