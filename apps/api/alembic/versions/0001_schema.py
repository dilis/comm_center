"""Initial schema: identity, messaging and authorization tables.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa

from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('contacts',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('type', sa.Enum('person', 'entity', name='contact_type'), server_default='person', nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contacts'))
    )
    op.create_index('ix_contacts_owner_id_deleted_at', 'contacts', ['owner_id', 'deleted_at'], unique=False)
    op.create_table('permission',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('resource', sa.String(length=32), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permission')),
    sa.UniqueConstraint('resource', 'action', name='uq_permission_resource_action')
    )
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('agent_direction', sa.Enum('inbound', 'outbound', name='agent_direction'), nullable=True),
    sa.Column('login_enabled', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('active_username', sa.String(length=64), sa.Computed('IF(deleted_at IS NULL, username, NULL)', persisted=False), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint('(is_system = 1 AND agent_direction IS NOT NULL) OR (is_system = 0 AND agent_direction IS NULL)', name=op.f('ck_users_agent_direction_iff_system')),
    sa.CheckConstraint('is_system = 0 OR (login_enabled = 0 AND password_hash IS NULL)', name=op.f('ck_users_system_agent_cannot_log_in')),
    sa.CheckConstraint('is_system = 0 OR deleted_at IS NULL', name=op.f('ck_users_system_agent_not_deletable')),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_users_contact_id')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_users_owner_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('active_username', name='uq_users_active_username'),
    sa.UniqueConstraint('contact_id', name='uq_users_contact_id')
    )
    op.create_index('ix_users_owner_id_deleted_at', 'users', ['owner_id', 'deleted_at'], unique=False)
    # contacts and users reference each other, so this key is added once both tables exist.
    op.create_foreign_key('fk_contacts_owner_id', 'contacts', 'users', ['owner_id'], ['id'])
    op.execute(
        """
        CREATE TRIGGER users_agent_fields_immutable BEFORE UPDATE ON users
        FOR EACH ROW
        BEGIN
          IF NOT (OLD.is_system <=> NEW.is_system)
             OR NOT (OLD.agent_direction <=> NEW.agent_direction) THEN
            SIGNAL SQLSTATE '45000'
              SET MESSAGE_TEXT = 'is_system and agent_direction are immutable';
          END IF;
        END
        """
    )
    op.create_table('access_group',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('active_name', sa.String(length=64), sa.Computed('IF(deleted_at IS NULL, name, NULL)', persisted=False), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_access_group_owner_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_access_group')),
    sa.UniqueConstraint('active_name', name='uq_access_group_active_name')
    )
    op.create_index('ix_access_group_owner_id_deleted_at', 'access_group', ['owner_id', 'deleted_at'], unique=False)
    op.create_table('contact_phone',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('phone_e164', sa.String(length=16), nullable=False),
    sa.Column('label', sa.String(length=32), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('active_phone', sa.String(length=16), sa.Computed('IF(deleted_at IS NULL, phone_e164, NULL)', persisted=False), nullable=True),
    sa.Column('active_primary_contact_id', sa.BigInteger(), sa.Computed('IF(deleted_at IS NULL AND is_primary = 1, contact_id, NULL)', persisted=False), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("phone_e164 REGEXP '^\\\\+[1-9][0-9]{6,14}$'", name=op.f('ck_contact_phone_e164')),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_contact_phone_contact_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contact_phone')),
    sa.UniqueConstraint('active_phone', name='uq_contact_phone_active_phone'),
    sa.UniqueConstraint('active_primary_contact_id', name='uq_contact_phone_active_primary')
    )
    op.create_index('ix_contact_phone_contact_id', 'contact_phone', ['contact_id'], unique=False)
    op.create_table('gsm_device',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('serial_port', sa.String(length=255), nullable=False),
    sa.Column('phone_number', sa.String(length=16), nullable=False),
    sa.Column('status', sa.Enum('online', 'offline', 'error', name='gsm_device_status'), server_default='offline', nullable=False),
    sa.Column('agent_user_id', sa.BigInteger(), nullable=False),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("phone_number REGEXP '^\\\\+[1-9][0-9]{6,14}$'", name=op.f('ck_gsm_device_e164')),
    sa.ForeignKeyConstraint(['agent_user_id'], ['users.id'], name=op.f('fk_gsm_device_agent_user_id')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_gsm_device_owner_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gsm_device')),
    sa.UniqueConstraint('agent_user_id', name='uq_gsm_device_agent_user_id')
    )
    op.create_index('ix_gsm_device_owner_id_deleted_at', 'gsm_device', ['owner_id', 'deleted_at'], unique=False)
    op.create_table('group_closure',
    sa.Column('ancestor_id', sa.BigInteger(), nullable=False),
    sa.Column('descendant_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['ancestor_id'], ['access_group.id'], name=op.f('fk_group_closure_ancestor_id')),
    sa.ForeignKeyConstraint(['descendant_id'], ['access_group.id'], name=op.f('fk_group_closure_descendant_id')),
    sa.PrimaryKeyConstraint('ancestor_id', 'descendant_id', name=op.f('pk_group_closure'))
    )
    op.create_table('group_group',
    sa.Column('parent_id', sa.BigInteger(), nullable=False),
    sa.Column('child_id', sa.BigInteger(), nullable=False),
    sa.CheckConstraint('parent_id <> child_id', name=op.f('ck_group_group_no_self_nesting')),
    sa.ForeignKeyConstraint(['child_id'], ['access_group.id'], name=op.f('fk_group_group_child_id')),
    sa.ForeignKeyConstraint(['parent_id'], ['access_group.id'], name=op.f('fk_group_group_parent_id')),
    sa.PrimaryKeyConstraint('parent_id', 'child_id', name=op.f('pk_group_group'))
    )
    op.create_table('group_permission',
    sa.Column('group_id', sa.BigInteger(), nullable=False),
    sa.Column('permission_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['access_group.id'], name=op.f('fk_group_permission_group_id')),
    sa.ForeignKeyConstraint(['permission_id'], ['permission.id'], name=op.f('fk_group_permission_permission_id')),
    sa.PrimaryKeyConstraint('group_id', 'permission_id', name=op.f('pk_group_permission'))
    )
    op.create_table('messages',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('channel', sa.Enum('gsm', name='message_channel'), nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('phone_number', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('queued', 'sending', 'sent', 'failed', 'delivered', 'received', name='message_status'), nullable=False),
    sa.Column('gsm_device_id', sa.BigInteger(), nullable=True),
    sa.Column('sent_at', sa.DateTime(), nullable=True),
    sa.Column('received_at', sa.DateTime(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("phone_number REGEXP '^\\\\+[1-9][0-9]{6,14}$'", name=op.f('ck_messages_e164')),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_messages_contact_id')),
    sa.ForeignKeyConstraint(['gsm_device_id'], ['gsm_device.id'], name=op.f('fk_messages_gsm_device_id')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_messages_owner_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    op.create_index('ix_messages_contact_id', 'messages', ['contact_id'], unique=False)
    op.create_index('ix_messages_owner_id_deleted_at', 'messages', ['owner_id', 'deleted_at'], unique=False)
    op.create_index('ix_messages_status_created_at', 'messages', ['status', 'created_at'], unique=False)
    op.create_table('user_group',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('group_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['access_group.id'], name=op.f('fk_user_group_group_id')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_group_user_id')),
    sa.PrimaryKeyConstraint('user_id', 'group_id', name=op.f('pk_user_group'))
    )


def downgrade() -> None:
    op.drop_table('user_group')
    op.drop_table('messages')
    op.drop_table('group_permission')
    op.drop_table('group_group')
    op.drop_table('group_closure')
    op.drop_table('gsm_device')
    op.drop_table('contact_phone')
    op.drop_table('access_group')
    op.drop_constraint('fk_contacts_owner_id', 'contacts', type_='foreignkey')
    op.execute('DROP TRIGGER IF EXISTS users_agent_fields_immutable')
    op.drop_table('users')
    op.drop_table('permission')
    op.drop_table('contacts')
