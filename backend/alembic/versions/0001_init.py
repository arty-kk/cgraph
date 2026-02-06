from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("root_path", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, index=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint("email", name="uq_user_email"),
    )

    op.create_table(
        "orgmembership",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), nullable=False, index=True),
        sa.Column("role", sa.String(), nullable=False, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint("org_id", "user_id", name="uq_orgmembership_org_user"),
    )

    op.create_table(
        "orgusage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, index=True),
        sa.Column("day", sa.Date(), nullable=False, index=True),
        sa.Column("kind", sa.String(), nullable=False, index=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("org_id", "day", "kind", name="uq_orgusage_org_day_kind"),
    )

    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("llm_enabled", sa.Boolean(), nullable=False),
        sa.Column("embeddings_enabled", sa.Boolean(), nullable=False),
        sa.Column("llm_daily_request_limit", sa.Integer(), nullable=True),
        sa.Column("embeddings_daily_chunk_limit", sa.Integer(), nullable=True),
        sa.Column("embeddings_daily_query_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint("name", name="uq_plan_name"),
    )

    op.create_table(
        "orgsubscription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, index=True),
        sa.Column("plan_id", sa.Integer(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, index=True),
        sa.Column("current_period_start", sa.DateTime(), nullable=False, index=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint("org_id", name="uq_orgsubscription_org_id"),
    )

    op.create_table(
        "orgentitlement",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, index=True),
        sa.Column("key", sa.String(), nullable=False, index=True),
        sa.Column("value_int", sa.Integer(), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint("org_id", "key", name="uq_orgentitlement_org_key"),
    )

    op.create_table(
        "usersession",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False, index=True),
        sa.Column("token_hash", sa.String(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True, index=True),
    )

    op.create_table(
        "apikey",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("token_prefix", sa.String(), nullable=False, index=True),
        sa.Column("token_hash", sa.String(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True, index=True),
    )

    op.create_table(
        "filenode",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("path", sa.String(), nullable=False, index=True),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("loc", sa.Integer(), nullable=False),
        sa.Column("complexity", sa.Integer(), nullable=False),
        sa.Column("fan_in", sa.Integer(), nullable=False),
        sa.Column("fan_out", sa.Integer(), nullable=False),
        sa.Column("scc_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("file_hash", sa.String(), nullable=False),
        sa.Column("file_mtime", sa.Float(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "path", name="uq_filenode_project_path"),
    )

    op.create_table(
        "fileedge",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("src_path", sa.String(), nullable=False, index=True),
        sa.Column("dst_path", sa.String(), nullable=False, index=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("raw", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "src_path",
            "dst_path",
            "kind",
            name="uq_fileedge_project_src_dst_kind",
        ),
    )

    op.create_table(
        "modulecontract",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("path", sa.String(), nullable=False, index=True),
        sa.Column("file_hash", sa.String(), nullable=False),
        sa.Column("contract_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("project_id", "path", name="uq_modulecontract_project_path"),
    )

    op.create_table(
        "analysisrun",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, index=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("target_path", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("dep_mode", sa.String(), nullable=True),
        sa.Column("retrieval", sa.String(), nullable=True),
        sa.Column("retrieval_settings_json", sa.Text(), nullable=True),
        sa.Column("apply_patch", sa.Boolean(), nullable=True),
        sa.Column("applied_json", sa.Text(), nullable=True),
        sa.Column("allowed_patch_paths_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
    )

    op.create_table(
        "taskjob",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, index=True),
        sa.Column("queue", sa.String(), nullable=False, index=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True, index=True),
    )

    op.create_table(
        "projectdoc",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("kind", sa.String(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
    )

    op.create_table(
        "reposnapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, index=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("content_sha256", sa.String(), nullable=False, index=True),
        sa.Column("archive_name", sa.String(), nullable=False),
        sa.Column("storage_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "apiroute",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("method", sa.String(), nullable=False, index=True),
        sa.Column("path", sa.String(), nullable=False, index=True),
        sa.Column("path_skeleton", sa.String(), nullable=False, index=True),
        sa.Column("router_prefix", sa.String(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=False, index=True),
        sa.Column("handler_name", sa.String(), nullable=False),
        sa.Column("lineno", sa.Integer(), nullable=False),
        sa.Column("decorator", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "method",
            "path",
            "source_path",
            "handler_name",
            "lineno",
            name="uq_apiroute_project_method_path_src_handler_line",
        ),
    )

    op.create_table(
        "apicall",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("method", sa.String(), nullable=False, index=True),
        sa.Column("path", sa.String(), nullable=False, index=True),
        sa.Column("path_skeleton", sa.String(), nullable=False, index=True),
        sa.Column("source_path", sa.String(), nullable=False, index=True),
        sa.Column("lineno", sa.Integer(), nullable=False),
        sa.Column("client", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "method",
            "path",
            "source_path",
            "lineno",
            name="uq_apicall_project_method_path_src_line",
        ),
    )

    op.create_table(
        "apiinclude",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("parent_source_path", sa.String(), nullable=False, index=True),
        sa.Column("parent_instance", sa.String(), nullable=False, index=True),
        sa.Column("child_source_path", sa.String(), nullable=False, index=True),
        sa.Column("child_instance", sa.String(), nullable=False, index=True),
        sa.Column("child_ref", sa.String(), nullable=False),
        sa.Column("child_module_spec", sa.String(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("lineno", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "parent_source_path",
            "parent_instance",
            "child_source_path",
            "child_instance",
            "prefix",
            "lineno",
            name="uq_apiinclude_project_parent_child_prefix_line",
        ),
    )

    op.create_table(
        "apiroutecontract",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("method", sa.String(), nullable=False, index=True),
        sa.Column("path", sa.String(), nullable=False, index=True),
        sa.Column("source_path", sa.String(), nullable=False, index=True),
        sa.Column("handler_name", sa.String(), nullable=False, index=True),
        sa.Column("lineno", sa.Integer(), nullable=False),
        sa.Column("contract_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "method",
            "path",
            "source_path",
            "handler_name",
            "lineno",
            name="uq_apiroutecontract_project_method_path_src_handler_line",
        ),
    )

    op.create_table(
        "apicallmeta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("method", sa.String(), nullable=False, index=True),
        sa.Column("path", sa.String(), nullable=False, index=True),
        sa.Column("source_path", sa.String(), nullable=False, index=True),
        sa.Column("lineno", sa.Integer(), nullable=False),
        sa.Column("wrapper_name", sa.String(), nullable=False),
        sa.Column("wrapper_response_type", sa.String(), nullable=False),
        sa.Column("wrapper_body_type", sa.String(), nullable=False),
        sa.Column("wrapper_params_json", sa.Text(), nullable=False),
        sa.Column("body_keys_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "method",
            "path",
            "source_path",
            "lineno",
            name="uq_apicallmeta_project_method_path_src_line",
        ),
    )

    op.create_table(
        "tstypedef",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=False, index=True),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("project_id", "name", "source_path", name="uq_tstypedef_project_name_src"),
    )

    op.create_table(
        "filechunkembedding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("path", sa.String(), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(), nullable=False, index=True),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.Column("symbol_name", sa.String(), nullable=False),
        sa.Column("symbol_start_line", sa.Integer(), nullable=False),
        sa.Column("symbol_end_line", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "path",
            "chunk_index",
            "file_hash",
            name="uq_filechunkembedding_project_path_chunk_hash",
        ),
    )

    op.create_table(
        "filetext",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("path", sa.String(), nullable=False, index=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True),
        ),
        sa.UniqueConstraint("project_id", "path", name="uq_filetext_project_path"),
    )
    op.create_index("ix_filetext_search", "filetext", ["search"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_filetext_search", table_name="filetext")
    op.drop_table("filetext")
    op.drop_table("filechunkembedding")
    op.drop_table("tstypedef")
    op.drop_table("apicallmeta")
    op.drop_table("apiroutecontract")
    op.drop_table("apiinclude")
    op.drop_table("apicall")
    op.drop_table("apiroute")
    op.drop_table("reposnapshot")
    op.drop_table("projectdoc")
    op.drop_table("taskjob")
    op.drop_table("analysisrun")
    op.drop_table("modulecontract")
    op.drop_table("fileedge")
    op.drop_table("filenode")
    op.drop_table("apikey")
    op.drop_table("usersession")
    op.drop_table("orgmembership")
    op.drop_table("orgusage")
    op.drop_table("orgentitlement")
    op.drop_table("orgsubscription")
    op.drop_table("plan")
    op.drop_table("user")
    op.drop_table("project")
    op.drop_table("organization")
