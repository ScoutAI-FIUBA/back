# Match Stats Query Specification

## Purpose

Define V1 retrieval and stats-attachment behavior for persisted matches.

## Requirements

### Requirement: Attach or Replace Match Stats After Creation

The system MUST support an explicit operation to attach or replace a match `stats` payload after a match exists, SHALL treat the payload as opaque JSONB in V1, and MUST NOT derive player mappings or recompute player aggregates from that payload in V1.

#### Scenario: Attach stats to an existing match

- GIVEN an owner-private match with `stats = null`
- WHEN the owner submits a stats payload
- THEN the payload is stored for that match

#### Scenario: Replace existing stats payload

- GIVEN a match that already has stored stats
- WHEN the owner submits a new stats payload
- THEN the previous payload is replaced by the new payload

#### Scenario: Do not derive player aggregates from attached stats

- GIVEN a submitted stats payload that contains player-level numbers
- WHEN the payload is attached to a persisted match
- THEN the system stores it without mapping JSON entries to players or recomputing `players.stats`

### Requirement: Return Match Stats With Participants

The system MUST return the persisted match stats payload together with that match's participants.

#### Scenario: Read match stats and participants

- GIVEN a match with stored stats and participant rows
- WHEN the owner requests that match's stats
- THEN the response includes the persisted stats payload and the participants for that match

#### Scenario: Read a match without stats

- GIVEN a match with `stats = null`
- WHEN the owner requests that match's stats
- THEN the response succeeds and returns null stats plus participants, if any

### Requirement: List Matches for a Known Player

The system MUST allow V1 listing of matches in which a known local player participated by filtering on participant linkage.

#### Scenario: List a player's participated matches

- GIVEN a local player linked from one or more participant rows
- WHEN the owner queries that player's match history
- THEN the response lists the matches linked through those participant rows

#### Scenario: Ignore unlinked participants for player history

- GIVEN participant rows without local player linkage
- WHEN the owner queries match history for a local player
- THEN only matches linked to that player's identifier are returned

### Requirement: Return Team Match Results Summary

The team stats endpoint MUST provide matches played, wins, losses, and match results for matches involving the requested team, and SHALL derive those outcomes from relational fields such as `winner_team_id` rather than parsing `matches.stats`.

#### Scenario: Read team results summary

- GIVEN persisted matches involving a team with known outcomes
- WHEN the owner requests team stats
- THEN the response includes matches played, wins, losses, and match results

#### Scenario: Ignore opaque stats payload for result calculation

- GIVEN a persisted match with opaque `stats` content and a stored `winner_team_id`
- WHEN the owner requests team stats
- THEN wins, losses, and match results are computed from the relational winner field without parsing the opaque payload

#### Scenario: Return empty team summary

- GIVEN a team with no persisted matches
- WHEN the owner requests team stats
- THEN the response returns zero played, zero wins, zero losses, and no match results
