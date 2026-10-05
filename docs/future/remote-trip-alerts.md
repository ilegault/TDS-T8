# Future effort — Remote trip alerts

Status: idea, not planned. Captured 2026-10-05 during the cold-start grilling.

## Why

The rig is meant to run unattended, sometimes overnight (8+ hour ramps), on a lab PC
nobody is sitting at. Trips already latch and show a banner (ADR 0003) and are written
to the Diagnostic log (ADR 0008), but nobody sees them until they walk up to the PC.

## The idea

When a trip latches, send a short message off the rig PC:

- trip kind and reason (the same sentence the banner shows),
- build ID, run ID, program block/phase, elapsed time,
- the last few heartbeat lines,
- optionally a camera snapshot (the C920s timelapse code already grabs frames).

Also worth considering: a "run finished" message, and a daily "rig idle and healthy"
heartbeat so silence is distinguishable from a dead PC.

## Open questions to grill before planning

1. Channel: email (SMTP via university account?), Slack webhook, or both?
2. Where do credentials live on the rig PC, and who can rotate them?
3. Does the rig PC have outbound network access on the lab VLAN?
4. What happens when sending fails — retry queue, logged WARNING, never blocks the
   Rig loop (it must run off the Rig thread).
5. Rate limiting so a flapping condition cannot send hundreds of messages.
6. Is any remote *control* wanted (acknowledge/reset a trip remotely)? This is a much
   bigger safety decision than alerts and should be its own ADR.
