-- Staging CT 610 only: what the customer dashboard reads (api/app/dashboard.py), for the role PhotonVox uses there. The call history's
-- columns the dashboard shows and nothing else of it (never the raw XML/JSON, recordings, PINs or network addresses), and the voicemail
-- messages' box, time and status (never the caller, the audio or a transcription). Production's read role has the first already and gets
-- the second in step P2 (docs/DEMO.md §5). Run as postgres in the fusionpbx database; running it again changes nothing.
--   ssh -i ~/.ssh/vox_staging root@10.10.0.60 'cd /tmp && su postgres -c "psql -v ON_ERROR_STOP=1 -d fusionpbx"' < engine/staging/dashboard-grants.sql
-- Undo: the same two statements as `revoke select (…) on … from photonvox_adapter` (the six door-call columns of v_xml_cdr were granted
-- before this, 2026-11-14: leave those).
grant select (xml_cdr_uuid, domain_uuid, leg, direction, caller_id_number, caller_destination, destination_number, start_epoch, answer_epoch,
              end_epoch, billsec, status, missed_call, voicemail_message, extension_uuid, hangup_cause) on v_xml_cdr to photonvox_adapter;
grant select (voicemail_message_uuid, domain_uuid, voicemail_uuid, created_epoch, message_status) on v_voicemail_messages to photonvox_adapter;
