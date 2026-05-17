DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
          AND t.relname = 'auth_refresh_sessions'
          AND c.contype = 'f'
          AND c.conname = 'auth_refresh_sessions_user_id_fkey'
          AND c.confdeltype <> 'c'
    ) THEN
        ALTER TABLE public.auth_refresh_sessions
            DROP CONSTRAINT auth_refresh_sessions_user_id_fkey;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
          AND t.relname = 'auth_refresh_sessions'
          AND c.contype = 'f'
          AND c.conname = 'auth_refresh_sessions_user_id_fkey'
          AND c.confdeltype = 'c'
    ) THEN
        ALTER TABLE public.auth_refresh_sessions
            ADD CONSTRAINT auth_refresh_sessions_user_id_fkey
                FOREIGN KEY (user_id)
                REFERENCES public.users (id)
                ON DELETE CASCADE;
    END IF;
END $$;
