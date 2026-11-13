-- GATE 1c: PhotonVox's read-only role on the live engine (CT 600, FusionPBX 5.5.12, PostgreSQL 18). Run by gate-1c.sh apply, which sets :'pw'.
-- Revised 2026-11-13 for Step 7, the in-place takeover of HUEPC (decision 32; Connor approved reading the dial plans): the import must see every
-- non-secret column of the rows PhotonVox will manage, so that its first publish can be proven a no-op. Grants are therefore "every column of
-- these tables except the secrets named below", generated from the catalog; gate-1c.sh verify lists what was granted.
-- Never readable: SIP passwords, voicemail PINs, menu PINs, gateway logins, FusionPBX users' passwords, salts, API keys and TOTP secrets,
-- recordings' audio, and the call records' raw XML/JSON, PINs, recordings and callers' network addresses.
\set ON_ERROR_STOP on
begin;
create role photonvox_ro login password :'pw' noinherit nocreatedb nocreaterole noreplication connection limit 4;
alter role photonvox_ro set default_transaction_read_only = on;
alter role photonvox_ro set statement_timeout = '15s';
alter role photonvox_ro set idle_in_transaction_session_timeout = '60s';
grant connect on database fusionpbx to photonvox_ro;
grant usage on schema public to photonvox_ro;

do $$
declare
  -- table => the columns it must never read
  secret constant jsonb := '{
    "v_domains": [],
    "v_extensions": ["password"],
    "v_extension_users": [],
    "v_voicemails": ["voicemail_password"],
    "v_destinations": [],
    "v_ivr_menus": ["ivr_menu_pin_number"],
    "v_ivr_menu_options": [],
    "v_ring_groups": [],
    "v_ring_group_destinations": [],
    "v_dialplans": [],
    "v_dialplan_details": [],
    "v_gateways": ["username", "password", "auth_username"],
    "v_recordings": ["recording_base64"],
    "v_users": ["password", "salt", "api_key", "user_totp_secret"],
    "v_xml_cdr": ["xml", "json", "pin_number", "network_addr", "record_path", "record_name", "record_length", "record_transcription", "sip_call_id"]
  }';
  t text;
  cols text;
begin
  for t in select jsonb_object_keys(secret) loop
    select string_agg(quote_ident(column_name), ', ' order by ordinal_position) into cols
      from information_schema.columns
     where table_schema = 'public' and table_name = t
       and not (column_name = any (select jsonb_array_elements_text(secret -> t)));
    if cols is null then raise exception 'table % not found', t; end if;
    execute format('grant select (%s) on public.%I to photonvox_ro', cols, t);
  end loop;
end $$;
commit;
