# Rollback / Uninstall

1. Stop the host process/CLI worker. This package does not install a background service by itself.
2. Revert Project instructions to the previously saved version; do not delete original `/uneXpected/` Library files.
3. For a prompt-improvement rollback, call `ImprovementGovernor.rollback(agent_id, target_version, reason, approval=approval_context)` only after a trusted host verifier has authenticated the approver and bound the context to `ImprovementGovernor.rollback_action_details(...)`. Without an injected production `ApprovalVerifier`, rollback is denied. Verify the active version in state after the authorized operation.
4. Back up `state/uneXpected.sqlite3` before any destructive action. Uninstall by removing only the v7 extraction directory and, if approved, its dedicated state directory.
5. Revoke any provider/API credentials through the provider's secure console if exposed; rotate secrets outside chat.
6. Confirm legacy profiles, v6 package and project files remain untouched.
