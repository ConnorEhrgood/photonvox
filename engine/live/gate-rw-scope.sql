-- PROPOSED, NOT APPLIED (audit VOX-B-1, 2026-11-21): limit photonvox_rw's writes to the domains PhotonVox manages, in the database itself.
-- gate-rw.sql grants insert, update and delete on nine tables with no row limit: PhotonVox scopes every statement to its domain, the role did
-- not. With this, a write by photonvox_rw to any other domain (or to a global row, domain_uuid null) is refused by Postgres.
--
-- How: row-level security on the nine tables with
--   * one PERMISSIVE policy for everyone (`to public using (true)`), so every other role (FusionPBX's own login if it is not the tables'
--     owner, photon_ro, photonvox_ro) reads and writes exactly as before; the tables' owner and superusers are not subject to RLS at all;
--   * RESTRICTIVE policies for photonvox_rw on insert, update and delete only: the row's domain must be in photonvox_managed_domain.
--     Reads are left alone on purpose: the writer's check that no other domain already answers a number reads other domains' numbers.
-- Run as postgres on CT 600, in a transaction, with the managed domain's uuid:
--   runuser -u postgres -- psql -d fusionpbx -v ON_ERROR_STOP=1 -v domain=<HUEPC domain_uuid> -f gate-rw-scope.sql
-- Check first (read only) who owns the nine tables and which roles log in, so nobody is cut off:
--   select tablename, tableowner from pg_tables where tablename like 'v\_%' and rowsecurity;   -- none should have RLS yet
-- Undo: the block at the end of this file (commented out).
-- Proved on a scratch Postgres 15 only (photonvox_rw refused on another domain and on a global row, allowed on its own; other roles
-- unchanged); not on FusionPBX's schema.
\set ON_ERROR_STOP on
begin;
create table if not exists photonvox_managed_domain (domain_uuid uuid primary key, note text not null default '', added_at timestamptz not null default now());
revoke all on photonvox_managed_domain from public;
grant select on photonvox_managed_domain to photonvox_rw;
insert into photonvox_managed_domain (domain_uuid, note) values (:'domain', 'adopted (decision 32)') on conflict do nothing;

do $$
declare t text;
begin
  foreach t in array array['v_extensions', 'v_voicemails', 'v_destinations', 'v_ivr_menus', 'v_ivr_menu_options', 'v_ring_groups',
                           'v_ring_group_destinations', 'v_dialplans', 'v_dialplan_details'] loop
    execute format('alter table %I enable row level security', t);
    execute format('create policy photonvox_everyone on %I as permissive for all to public using (true) with check (true)', t);
    execute format('create policy photonvox_rw_insert on %I as restrictive for insert to photonvox_rw '
                   'with check (domain_uuid in (select domain_uuid from photonvox_managed_domain))', t);
    execute format('create policy photonvox_rw_update on %I as restrictive for update to photonvox_rw '
                   'using (domain_uuid in (select domain_uuid from photonvox_managed_domain)) '
                   'with check (domain_uuid in (select domain_uuid from photonvox_managed_domain))', t);
    execute format('create policy photonvox_rw_delete on %I as restrictive for delete to photonvox_rw '
                   'using (domain_uuid in (select domain_uuid from photonvox_managed_domain))', t);
  end loop;
end $$;
commit;

-- Undo:
-- begin;
-- do $$ declare t text; begin
--   foreach t in array array['v_extensions', 'v_voicemails', 'v_destinations', 'v_ivr_menus', 'v_ivr_menu_options', 'v_ring_groups',
--                            'v_ring_group_destinations', 'v_dialplans', 'v_dialplan_details'] loop
--     execute format('drop policy if exists photonvox_rw_delete on %I', t);
--     execute format('drop policy if exists photonvox_rw_update on %I', t);
--     execute format('drop policy if exists photonvox_rw_insert on %I', t);
--     execute format('drop policy if exists photonvox_everyone on %I', t);
--     execute format('alter table %I disable row level security', t);
--   end loop; end $$;
-- drop table if exists photonvox_managed_domain;
-- commit;
