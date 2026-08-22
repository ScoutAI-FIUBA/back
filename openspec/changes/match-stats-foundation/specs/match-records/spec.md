# Match Records Specification

## Purpose

Define owner-private match storage, metadata, and participant linkage for V1.

## Requirements

### Requirement: Create Owner-Private Match Records

The system MUST create match records scoped to the owning user and SHALL preserve existing data through additive migration only.

#### Scenario: Create a match with existing teams

- GIVEN an owner and two existing teams visible to that owner
- WHEN the owner creates a match with home team, away team, played date, and optional description
- THEN the match is stored as owner-private with nullable `stats`

#### Scenario: Reject unknown or inaccessible teams

- GIVEN a create request referencing a team the owner does not own or cannot access
- WHEN the request is submitted
- THEN the system rejects match creation

### Requirement: Match Metadata Rules

The system MUST store the actual played date, MAY store free-text description, MUST NOT require stats payload during creation, and MUST include nullable `winner_team_id` for later outcome persistence.

#### Scenario: Create without stats payload

- GIVEN a valid create request without stats
- WHEN the match is persisted
- THEN the stored match has `stats = null` and `winner_team_id = null`

#### Scenario: Preserve free-text description

- GIVEN a valid create request with description text
- WHEN the match is persisted and later retrieved
- THEN the same description is returned unchanged

#### Scenario: Persist only valid winners

- GIVEN a persisted match whose final outcome is later known
- WHEN the winner is stored
- THEN `winner_team_id` references either the home team or the away team for that match

### Requirement: Protect Teams Referenced By Matches

The system MUST prevent deletion of a team that is referenced by any persisted match and SHALL return HTTP 409 with error code `TEAM_HAS_MATCHES`.

#### Scenario: Reject deletion of a referenced team

- GIVEN a team referenced as the home or away team of at least one persisted match
- WHEN the owner requests deletion of that team
- THEN the request is rejected with HTTP 409 and error code `TEAM_HAS_MATCHES`

#### Scenario: Allow deletion of an unreferenced team

- GIVEN a team owned by the requester and not referenced by any persisted match
- WHEN the owner requests deletion of that team
- THEN the team is deleted successfully

### Requirement: Manage Lightweight Match Participants

The system MUST store match participants separately from matches, and each participant row MAY link to a local player or remain unlinked.

#### Scenario: Attach participants with mixed linkage

- GIVEN a match and participant data where some entries map to local players and others do not
- WHEN participants are stored
- THEN each participant is persisted and unlinked entries remain valid with null player linkage

#### Scenario: Preserve participants when player linkage is absent

- GIVEN a participant entry without a local player match
- WHEN the participant is saved
- THEN the system stores the participant without requiring player creation or resolution
