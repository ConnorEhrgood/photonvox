-- PhotonVox's write role on the live engine (CT 600), Step 7 of the takeover (decision 32). Run by gate-rw.sh apply, which sets :'pw'.
-- It reads what photonvox_ro reads (it is a member: every non-secret column of 15 tables) and may insert, update and delete rows in the nine
-- tables PhotonVox writes, and nothing else: no other table, no schema change, no other database. It cannot read SIP passwords or voicemail PINs
-- (the writer keeps an existing secret by never touching it). PhotonVox scopes every statement to the domain it manages; the role does not.
\set ON_ERROR_STOP on
begin;
create role photonvox_rw login password :'pw' inherit nocreatedb nocreaterole noreplication connection limit 4;
grant photonvox_ro to photonvox_rw;
alter role photonvox_rw set statement_timeout = '15s';
alter role photonvox_rw set idle_in_transaction_session_timeout = '60s';
grant connect on database fusionpbx to photonvox_rw;
grant insert, update, delete on v_extensions, v_voicemails, v_destinations, v_ivr_menus, v_ivr_menu_options, v_ring_groups,
      v_ring_group_destinations, v_dialplans, v_dialplan_details to photonvox_rw;
commit;
