from __future__ import annotations

from fastapi import FastAPI

from src.interfaces.http.bootstrap.dependencies import HttpDependencies
from src.interfaces.http.routes.auth_router import create_auth_router
from src.interfaces.http.routes.players_router import create_players_router
from src.interfaces.http.routes.team_router import create_team_router
from src.interfaces.http.routes.videos_router import create_videos_router


def wire_routers(app: FastAPI, deps: HttpDependencies) -> None:
    """Registers all route groups with fully constructed use-case dependencies.

    This function is the HTTP boundary assembly point; route factories remain
    free of container knowledge and only receive explicit collaborators.
    """

    app.include_router(
        create_auth_router(
            register_use_case=deps.register_user_use_case,
            login_use_case=deps.login_use_case,
            refresh_use_case=deps.refresh_session_use_case,
            logout_use_case=deps.logout_use_case,
            current_user_use_case=deps.get_current_user_use_case,
            delete_current_user_use_case=deps.delete_current_user_use_case,
            access_token_resolver=deps.access_token_resolver.resolve_subject,
        )
    )
    app.include_router(
        create_team_router(
            create_team_use_case=deps.create_team_use_case,
            list_teams_use_case=deps.list_teams_use_case,
            update_team_use_case=deps.update_team_use_case,
            delete_team_use_case=deps.delete_team_use_case,
        )
    )
    app.include_router(
        create_players_router(
            create_player_use_case=deps.create_player_use_case,
            list_players_use_case=deps.list_players_use_case,
            list_players_by_team_use_case=deps.list_players_by_team_use_case,
            update_player_use_case=deps.update_player_use_case,
            delete_player_use_case=deps.delete_player_use_case,
            assign_player_team_use_case=deps.assign_player_team_use_case,
        )
    )
    app.include_router(
        create_videos_router(
            init_upload_use_case=deps.init_video_upload_use_case,
            complete_upload_use_case=deps.complete_video_upload_use_case,
            abort_upload_use_case=deps.abort_video_upload_use_case,
            list_videos_use_case=deps.list_videos_use_case,
            get_video_use_case=deps.get_video_use_case,
            update_video_use_case=deps.update_video_use_case,
            delete_video_use_case=deps.delete_video_use_case,
        )
    )
