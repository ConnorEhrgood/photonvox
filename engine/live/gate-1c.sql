-- GATE 1c: PhotonVox's read-only role on the live engine (CT 600, FusionPBX 5.5.12, PostgreSQL 18). Run by gate-1c.sh apply, which sets :'pw'.
-- What Step 1 shows of each live domain (monitored only): domains, extensions, voicemail boxes, numbers, menus, ring groups, upstreams by name,
-- and call history. Columns are granted one by one: no SIP or voicemail passwords, menu PINs, gateway logins, CDR raw XML/JSON, recordings or
-- callers' network addresses. Nothing of FusionPBX's own users. The dial plans (needed for R2's comparison) are not granted until R2.
\set ON_ERROR_STOP on
begin;
create role photonvox_ro login password :'pw' noinherit nocreatedb nocreaterole noreplication connection limit 4;
alter role photonvox_ro set default_transaction_read_only = on;
alter role photonvox_ro set statement_timeout = '15s';
alter role photonvox_ro set idle_in_transaction_session_timeout = '60s';
grant connect on database fusionpbx to photonvox_ro;
grant usage on schema public to photonvox_ro;

grant select (domain_uuid, domain_parent_uuid, domain_name, domain_enabled, domain_description) on v_domains to photonvox_ro;
grant select (extension_uuid, domain_uuid, extension, number_alias, accountcode, effective_caller_id_name, effective_caller_id_number,
              outbound_caller_id_name, outbound_caller_id_number, emergency_caller_id_name, emergency_caller_id_number, directory_first_name,
              directory_last_name, max_registrations, limit_max, user_context, toll_allow, call_timeout, call_group, user_record, do_not_disturb,
              forward_all_enabled, forward_all_destination, forward_busy_enabled, forward_busy_destination, forward_no_answer_enabled,
              forward_no_answer_destination, forward_user_not_registered_enabled, forward_user_not_registered_destination, follow_me_enabled,
              enabled, description, insert_date, update_date) on v_extensions to photonvox_ro;
grant select (voicemail_uuid, domain_uuid, voicemail_id, voicemail_mail_to, voicemail_attach_file, voicemail_local_after_email,
              voicemail_enabled, voicemail_description) on v_voicemails to photonvox_ro;
grant select (destination_uuid, domain_uuid, dialplan_uuid, destination_type, destination_number, destination_prefix, destination_context,
              destination_caller_id_name, destination_caller_id_number, destination_actions, destination_app, destination_data,
              destination_type_emergency, destination_enabled, destination_description, insert_date, update_date) on v_destinations to photonvox_ro;
grant select (ivr_menu_uuid, domain_uuid, dialplan_uuid, ivr_menu_name, ivr_menu_extension, ivr_menu_greet_long, ivr_menu_greet_short,
              ivr_menu_timeout, ivr_menu_exit_app, ivr_menu_exit_data, ivr_menu_direct_dial, ivr_menu_enabled, ivr_menu_description) on v_ivr_menus to photonvox_ro;
grant select (ivr_menu_option_uuid, ivr_menu_uuid, domain_uuid, ivr_menu_option_digits, ivr_menu_option_action, ivr_menu_option_param,
              ivr_menu_option_order, ivr_menu_option_description, ivr_menu_option_enabled) on v_ivr_menu_options to photonvox_ro;
grant select (ring_group_uuid, domain_uuid, dialplan_uuid, ring_group_name, ring_group_extension, ring_group_strategy, ring_group_call_timeout,
              ring_group_timeout_app, ring_group_timeout_data, ring_group_forward_enabled, ring_group_forward_destination, ring_group_enabled,
              ring_group_description) on v_ring_groups to photonvox_ro;
grant select (ring_group_destination_uuid, ring_group_uuid, domain_uuid, destination_number, destination_delay, destination_timeout,
              destination_enabled) on v_ring_group_destinations to photonvox_ro;
grant select (gateway_uuid, domain_uuid, gateway, proxy, register, context, profile, enabled, description) on v_gateways to photonvox_ro;
grant select (xml_cdr_uuid, domain_uuid, domain_name, extension_uuid, direction, caller_id_name, caller_id_number, caller_destination,
              destination_number, start_stamp, answer_stamp, end_stamp, duration, billsec, missed_call, voicemail_message, hangup_cause, status,
              call_disposition, ring_group_uuid, ivr_menu_uuid, leg, originating_leg_uuid) on v_xml_cdr to photonvox_ro;
commit;
