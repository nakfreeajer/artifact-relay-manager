# Protected Areas

## Repository boundary
Writable project:
- `nakfreeajer/artifact-relay-manager`

Foreign repositories are outside this project's mutation scope unless a future human-authorized milestone explicitly changes that boundary.

## Forbidden product authority
Do not add Relay logic that:
- selects milestones or prompts;
- launches/relaunches Executor work;
- accepts/rejects implementation;
- decides Architect rollover priority;
- authorizes workflow retry;
- infers workflow meaning from arbitrary artifact contents.

## Secrets and private state
Never commit OAuth tokens, cookies, browser profiles, authenticated URLs, credentials, raw customer/production data, or the full `.agent-work/` tree.

## Transport boundary
Only explicitly configured project folders may be monitored. Project identity mismatch is a hard stop.
