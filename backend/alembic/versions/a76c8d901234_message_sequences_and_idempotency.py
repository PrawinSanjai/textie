"""Add ordered message cursors and client idempotency keys.

Revision ID: a76c8d901234
Revises: d4f9c2e1a7b3
"""
from alembic import op
import sqlalchemy as sa

revision = "a76c8d901234"
down_revision = "d4f9c2e1a7b3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("last_message_sequence", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("messages", sa.Column("sequence", sa.BigInteger(), nullable=True))
    op.add_column("messages", sa.Column("client_message_id", sa.Uuid(), nullable=True))
    op.execute(sa.text("""
        WITH numbered AS (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY sent_at, id) AS seq
            FROM messages
        )
        UPDATE messages SET sequence = numbered.seq FROM numbered WHERE messages.id = numbered.id
    """))
    op.execute(sa.text("""
        UPDATE conversations SET last_message_sequence = COALESCE(
            (SELECT MAX(sequence) FROM messages WHERE messages.conversation_id = conversations.id), 0
        )
    """))
    op.alter_column("messages", "sequence", nullable=False)
    op.create_unique_constraint("uq_messages_conversation_sequence", "messages", ["conversation_id", "sequence"])
    op.create_unique_constraint("uq_messages_participant_client_id", "messages", ["participant_id", "client_message_id"])


def downgrade():
    op.drop_constraint("uq_messages_participant_client_id", "messages", type_="unique")
    op.drop_constraint("uq_messages_conversation_sequence", "messages", type_="unique")
    op.drop_column("messages", "client_message_id")
    op.drop_column("messages", "sequence")
    op.drop_column("conversations", "last_message_sequence")
