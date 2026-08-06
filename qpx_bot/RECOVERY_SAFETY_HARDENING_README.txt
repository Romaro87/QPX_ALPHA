QPX RECOVERY AND KILL-SWITCH SAFETY HARDENING
=============================================

This milestone closes two recovery-control risks.

1. Verified restore locking
---------------------------

The restore path already holds the backup lock. Its required
pre-restore safety snapshot now reuses that held lock instead of trying
to acquire the same non-reentrant lock a second time.

The restore test performs a complete temporary disaster-recovery cycle:

- create and verify an original archive;
- mutate the live paper state;
- create a pre-restore safety snapshot;
- restore the original archive;
- verify the restored state checksum and audit chain;
- verify that the backup lock is released;
- leave a restore-owned paper kill switch active.

Restore also refuses to run while paper, operations, or qualification
runtime locks are active.

2. Kill-switch ownership
------------------------

KILL_SWITCH now records an owner.

Recognized owners:

manual
    An independent manual safety hold.

operations_circuit_breaker
    A hold created by automated operations after repeated failures.

restore_guard
    A hold created during verified disaster recovery.

The operations circuit breaker no longer overwrites an existing manual
or restore-owned paper kill switch.

The normal operations resume command:

python QPX_RUN_DAILY_OPERATIONS.py --resume

clears only an operations_circuit_breaker kill switch. An independent
manual or restore guard remains active.

After a verified restore, review the backup, operations, session, and
qualification reports. Then explicitly clear only the restore-owned
guard with:

python QPX_RUN_DAILY_OPERATIONS.py \
    --resume-restored-paper \
    --confirm-resume-restored-paper

That command validates the restored paper state and audit chain before
removing the restore guard. It refuses to remove a manual or
operations-owned kill switch.

This remains simulated paper trading. Broker connectivity is disabled.
