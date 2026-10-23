from __future__ import annotations

from fastapi import FastAPI

from src.interfaces.http.bootstrap.dependencies import HttpDependencies
from src.interfaces.http.routes.clip_collections_router import create_clip_collections_router
from src.interfaces.http.routes.auth_router import create_auth_router
from src.interfaces.http.routes.jobs_router import create_jobs_router
from src.interfaces.http.routes.matches_router import create_matches_router
from src.interfaces.http.routes.stats_router import create_stats_router
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
            request_password_reset_use_case=deps.request_password_reset_use_case,
            reset_password_use_case=deps.reset_password_use_case,
            change_password_use_case=deps.change_password_use_case,
            update_profile_use_case=deps.update_profile_use_case,
            send_email_verification_use_case=deps.send_email_verification_use_case,
            confirm_email_verification_use_case=deps.confirm_email_verification_use_case,
            google_login_use_case=deps.google_login_use_case,
        )
    )
    app.include_router(
        create_team_router(
            create_team_use_case=deps.create_team_use_case,
            list_teams_use_case=deps.list_teams_use_case,
            update_team_use_case=deps.update_team_use_case,
            delete_team_use_case=deps.delete_team_use_case,
            get_team_stats_use_case=deps.get_team_stats_use_case,
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
            get_player_stats_use_case=deps.get_player_stats_use_case,
            get_player_matches_use_case=deps.get_player_matches_use_case,
            get_player_shot_chart_use_case=deps.get_player_shot_chart_use_case,
            get_player_analysis_stats_use_case=deps.get_player_analysis_stats_use_case,
            catch_up=deps.catch_up_player_analysis_use_case,
        )
    )
    app.include_router(
        create_matches_router(
            create_match_use_case=deps.create_match_use_case,
            list_matches_use_case=deps.list_matches_use_case,
            get_match_use_case=deps.get_match_use_case,
            replace_match_stats_use_case=deps.replace_match_stats_use_case,
            get_match_stats_use_case=deps.get_match_stats_use_case,
            preview_stats_import_use_case=deps.preview_stats_import_use_case,
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
    app.include_router(
        create_clip_collections_router(
            create_collection_use_case=deps.create_clip_collection_use_case,
            list_collections_use_case=deps.list_clip_collections_use_case,
            get_collection_detail_use_case=deps.get_clip_collection_detail_use_case,
            add_clip_use_case=deps.add_clip_use_case,
            add_clip_batch_use_case=deps.add_clip_batch_use_case,
            delete_item_use_case=deps.delete_clip_collection_item_use_case,
            export_clip_item_use_case=deps.export_clip_item_use_case,
            update_clip_description_use_case=deps.update_clip_description_use_case,
        )
    )
    app.include_router(
        create_jobs_router(
            submit_job_use_case=deps.submit_processing_job_use_case,
            get_job_use_case=deps.get_processing_job_use_case,
            list_video_jobs_use_case=deps.list_video_jobs_use_case,
            record_job_progress_use_case=deps.record_job_progress_use_case,
            get_job_results_use_case=deps.get_job_results_use_case,
            set_team_side_use_case=deps.set_job_team_side_use_case,
            callback_token=deps.processing_callback_token,
        )
    )
    app.include_router(
        create_stats_router(
            game_stats_use_case=deps.game_stats_use_case,
            court_positions_use_case=deps.court_positions_use_case,
            shot_chart_use_case=deps.shot_chart_use_case,
            team_sides_use_case=deps.team_sides_use_case,
            similar_clips_use_case=deps.similar_clips_use_case,
            events_use_case=deps.events_use_case,
        )
    )
