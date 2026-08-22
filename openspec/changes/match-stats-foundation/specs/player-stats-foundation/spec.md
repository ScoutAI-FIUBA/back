# Player Stats Foundation Specification

## Purpose

Define V1 global player stats exposure and storage foundation.

## Requirements

### Requirement: Initialize Fixed Player Stats Aggregate

The system MUST add `players.stats` as a fixed initialized JSONB aggregate structure through additive migration and SHALL preserve pre-existing player data.

#### Scenario: Existing player receives initialized stats

- GIVEN a player created before the migration
- WHEN the additive migration is applied
- THEN the player has an initialized `stats` value using the fixed V1 structure

#### Scenario: New player receives initialized stats

- GIVEN a player created after the migration
- WHEN the player is persisted
- THEN the player starts with the same initialized `stats` structure

### Requirement: Expose Global Player Stats Only

The player stats endpoint MUST return the player's global persisted stats and MUST NOT require per-match recomputation in V1.

#### Scenario: Read global player stats

- GIVEN a known player with persisted `stats`
- WHEN the owner requests player stats
- THEN the response returns that player's global stats payload

#### Scenario: Do not derive player stats from match payloads

- GIVEN matches whose stats payloads contain player-related data
- WHEN the owner requests player stats
- THEN the response is based only on persisted player aggregate data already stored on the player
