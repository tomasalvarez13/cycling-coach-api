"""strava oauth and activities

Revision ID: 20260405_0002
Revises: 20260404_0001
Create Date: 2026-04-05 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260405_0002"
down_revision = "20260404_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_user_id", sa.String(length=128), nullable=False),
        sa.Column("access_token", sa.String(length=512), nullable=False),
        sa.Column("refresh_token", sa.String(length=512), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_oauth_connections_user_id", "oauth_connections", ["user_id"], unique=False)
    op.create_index("ix_oauth_connections_provider", "oauth_connections", ["provider"], unique=False)
    op.create_index(
        "ix_oauth_connections_provider_user_id",
        "oauth_connections",
        ["provider_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_oauth_connections_token_expires_at",
        "oauth_connections",
        ["token_expires_at"],
        unique=False,
    )
    op.create_index("ix_oauth_connections_last_sync_at", "oauth_connections", ["last_sync_at"], unique=False)
    op.create_index("ix_oauth_connections_is_active", "oauth_connections", ["is_active"], unique=False)

    op.create_table(
        "sync_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sync_jobs_user_id", "sync_jobs", ["user_id"], unique=False)
    op.create_index("ix_sync_jobs_provider", "sync_jobs", ["provider"], unique=False)
    op.create_index("ix_sync_jobs_job_type", "sync_jobs", ["job_type"], unique=False)
    op.create_index("ix_sync_jobs_status", "sync_jobs", ["status"], unique=False)
    op.create_index("ix_sync_jobs_created_at", "sync_jobs", ["created_at"], unique=False)

    op.create_table(
        "strava_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider_activity_id", sa.String(length=64), nullable=False),
        sa.Column("athlete_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sport_type", sa.String(length=64), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=128), nullable=True),
        sa.Column("distance_meters", sa.Float(), nullable=True),
        sa.Column("moving_time_seconds", sa.Integer(), nullable=True),
        sa.Column("elapsed_time_seconds", sa.Integer(), nullable=True),
        sa.Column("total_elevation_gain", sa.Float(), nullable=True),
        sa.Column("average_speed_mps", sa.Float(), nullable=True),
        sa.Column("max_speed_mps", sa.Float(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider_activity_id", name="uq_strava_activities_provider_activity_id"),
    )
    op.create_index("ix_strava_activities_user_id", "strava_activities", ["user_id"], unique=False)
    op.create_index(
        "ix_strava_activities_provider_activity_id",
        "strava_activities",
        ["provider_activity_id"],
        unique=False,
    )
    op.create_index("ix_strava_activities_athlete_id", "strava_activities", ["athlete_id"], unique=False)
    op.create_index("ix_strava_activities_sport_type", "strava_activities", ["sport_type"], unique=False)
    op.create_index("ix_strava_activities_start_date", "strava_activities", ["start_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_strava_activities_start_date", table_name="strava_activities")
    op.drop_index("ix_strava_activities_sport_type", table_name="strava_activities")
    op.drop_index("ix_strava_activities_athlete_id", table_name="strava_activities")
    op.drop_index("ix_strava_activities_provider_activity_id", table_name="strava_activities")
    op.drop_index("ix_strava_activities_user_id", table_name="strava_activities")
    op.drop_table("strava_activities")

    op.drop_index("ix_sync_jobs_created_at", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_status", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_job_type", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_provider", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_user_id", table_name="sync_jobs")
    op.drop_table("sync_jobs")

    op.drop_index("ix_oauth_connections_is_active", table_name="oauth_connections")
    op.drop_index("ix_oauth_connections_last_sync_at", table_name="oauth_connections")
    op.drop_index("ix_oauth_connections_token_expires_at", table_name="oauth_connections")
    op.drop_index("ix_oauth_connections_provider_user_id", table_name="oauth_connections")
    op.drop_index("ix_oauth_connections_provider", table_name="oauth_connections")
    op.drop_index("ix_oauth_connections_user_id", table_name="oauth_connections")
    op.drop_table("oauth_connections")
