-- =============================================================================
-- pg_drop_all_objects.sql
-- Drops ALL user-created objects in the 'public' schema:
--   tables, views, materialized views, functions, procedures,
--   triggers, sequences, and types.
--
-- Usage:
--   psql -U <user> -d <database> -f pg_drop_all_objects.sql
--
-- WARNING: This is IRREVERSIBLE. Back up your data first.
--   pg_dump -U <user> <database> > backup.sql
-- =============================================================================

DO $$
DECLARE
    r RECORD;
BEGIN

    -- -------------------------------------------------------------------------
    -- 1. TRIGGERS
    --    Must be dropped before their tables.
    -- -------------------------------------------------------------------------
    FOR r IN
        SELECT
            trigger_name,
            event_object_table
        FROM information_schema.triggers
        WHERE trigger_schema = 'public'
        GROUP BY trigger_name, event_object_table
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON %I.%I CASCADE',
            r.trigger_name, 'public', r.event_object_table
        );
        RAISE NOTICE 'Dropped trigger: % on %', r.trigger_name, r.event_object_table;
    END LOOP;

    -- -------------------------------------------------------------------------
    -- 2. VIEWS  (standard views)
    -- -------------------------------------------------------------------------
    FOR r IN
        SELECT table_name
        FROM information_schema.views
        WHERE table_schema = 'public'
    LOOP
        EXECUTE format('DROP VIEW IF EXISTS %I.%I CASCADE', 'public', r.table_name);
        RAISE NOTICE 'Dropped view: %', r.table_name;
    END LOOP;

    -- -------------------------------------------------------------------------
    -- 3. MATERIALIZED VIEWS
    -- -------------------------------------------------------------------------
    FOR r IN
        SELECT matviewname
        FROM pg_matviews
        WHERE schemaname = 'public'
    LOOP
        EXECUTE format('DROP MATERIALIZED VIEW IF EXISTS %I.%I CASCADE', 'public', r.matviewname);
        RAISE NOTICE 'Dropped materialized view: %', r.matviewname;
    END LOOP;

    -- -------------------------------------------------------------------------
    -- 4. TABLES
    -- -------------------------------------------------------------------------
    FOR r IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I.%I CASCADE', 'public', r.tablename);
        RAISE NOTICE 'Dropped table: %', r.tablename;
    END LOOP;

    -- -------------------------------------------------------------------------
    -- 5. SEQUENCES
    --    Sequences owned by dropped table columns are already gone via CASCADE,
    --    but standalone sequences need explicit removal.
    -- -------------------------------------------------------------------------
    FOR r IN
        SELECT sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = 'public'
    LOOP
        EXECUTE format('DROP SEQUENCE IF EXISTS %I.%I CASCADE', 'public', r.sequence_name);
        RAISE NOTICE 'Dropped sequence: %', r.sequence_name;
    END LOOP;

    -- -------------------------------------------------------------------------
    -- 6. FUNCTIONS & PROCEDURES
    --    pg_proc covers both FUNCTION (prokind = 'f') and PROCEDURE (prokind = 'p').
    --    pg_get_function_identity_arguments produces the correct argument signature
    --    needed to uniquely identify overloaded routines.
    -- -------------------------------------------------------------------------
    FOR r IN
        SELECT
            p.proname                                          AS routine_name,
            pg_get_function_identity_arguments(p.oid)         AS args,
            CASE p.prokind
                WHEN 'p' THEN 'PROCEDURE'
                ELSE 'FUNCTION'
            END                                                AS kind
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.prokind IN ('f', 'p')   -- functions and procedures only
    LOOP
        EXECUTE format(
            'DROP %s IF EXISTS %I.%I(%s) CASCADE',
            r.kind, 'public', r.routine_name, r.args
        );
        RAISE NOTICE 'Dropped %: %(%)', r.kind, r.routine_name, r.args;
    END LOOP;

    -- -------------------------------------------------------------------------
    -- 7. USER-DEFINED TYPES  (composite, enum, domain, range, base)
    --    Excludes pseudo-types and built-ins.
    -- -------------------------------------------------------------------------
    FOR r IN
        SELECT t.typname
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname  = 'public'
          AND t.typtype  IN ('c', 'e', 'd', 'r', 'b')  -- composite/enum/domain/range/base
          AND NOT EXISTS (                               -- skip auto-generated array types
              SELECT 1 FROM pg_type arr
              WHERE arr.typelem = t.oid
          )
    LOOP
        EXECUTE format('DROP TYPE IF EXISTS %I.%I CASCADE', 'public', r.typname);
        RAISE NOTICE 'Dropped type: %', r.typname;
    END LOOP;

END $$;