"""A roster change re-syncs the team's latest analyses in the background, best effort."""

from __future__ import annotations

import unittest

from src.application.stats.player_analysis import ResyncTeamAnalysesUseCase

from tests.interfaces.http.test_players_router import OTHER_TEAM_ID, TEAM_ID, VALID, _TeamRepo, build_client


class _Resync:
    def __init__(self) -> None:
        self.teams: list[str] = []

    def execute(self, team_id: str) -> int:
        self.teams.append(team_id)
        return 0


def _client(resync, *teams: str):
    owned = _TeamRepo()
    for team in teams:
        owned.owned.add((team, "scout-1"))
    return build_client(team_repo=owned, resync_team=resync)[0]


class TestRosterResync(unittest.TestCase):
    def test_creating_a_free_agent_has_no_team_to_re_sync(self) -> None:
        resync = _Resync()
        self.assertEqual(_client(resync).post("/players", json=VALID).status_code, 201)
        self.assertEqual(resync.teams, [])

    def test_updating_a_player_re_syncs_their_team(self) -> None:
        resync = _Resync()
        client = _client(resync, TEAM_ID)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        client.put(f"/players/{pid}/team/{TEAM_ID}")
        resync.teams.clear()
        response = client.put(f"/players/{pid}", json={**VALID, "jersey_number": "9"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resync.teams, [TEAM_ID])

    def test_assigning_a_team_re_syncs_the_new_team_and_the_old_one(self) -> None:
        resync = _Resync()
        client = _client(resync, TEAM_ID, OTHER_TEAM_ID)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        client.put(f"/players/{pid}/team/{TEAM_ID}")
        self.assertEqual(resync.teams, [TEAM_ID])  # a free agent has no old team
        resync.teams.clear()
        client.put(f"/players/{pid}/team/{OTHER_TEAM_ID}")
        self.assertEqual(resync.teams, [TEAM_ID, OTHER_TEAM_ID])

    def test_deleting_a_player_re_syncs_the_team_they_had(self) -> None:
        resync = _Resync()
        client = _client(resync, TEAM_ID)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        client.put(f"/players/{pid}/team/{TEAM_ID}")
        resync.teams.clear()
        self.assertEqual(client.delete(f"/players/{pid}").status_code, 204)
        self.assertEqual(resync.teams, [TEAM_ID])

    def test_a_failed_request_re_syncs_nothing(self) -> None:
        resync = _Resync()
        client = _client(resync, TEAM_ID)
        missing = "00000000-0000-4000-8000-0000000000ff"
        self.assertEqual(client.delete(f"/players/{missing}").status_code, 404)
        self.assertEqual(client.put(f"/players/{missing}/team/{TEAM_ID}").status_code, 404)
        self.assertEqual(resync.teams, [])

    def test_a_re_sync_that_blows_up_never_reaches_the_request(self) -> None:
        class _BrokenJobs:
            def list_done_with_side_by_team(self, **_):
                raise RuntimeError("db down")

        client = _client(ResyncTeamAnalysesUseCase(jobs=_BrokenJobs(), sync=object()), TEAM_ID)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        self.assertEqual(client.put(f"/players/{pid}/team/{TEAM_ID}").status_code, 200)
        self.assertEqual(client.delete(f"/players/{pid}").status_code, 204)

    def test_without_a_resync_use_case_nothing_changes(self) -> None:
        client = _client(None, TEAM_ID)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        self.assertEqual(client.put(f"/players/{pid}/team/{TEAM_ID}").status_code, 200)
        self.assertEqual(client.delete(f"/players/{pid}").status_code, 204)


if __name__ == "__main__":
    unittest.main()
