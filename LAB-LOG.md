# Lab log

A running record of build decisions and the reasoning behind them.
Newest entries at the bottom.

---

## Environment

- MacBook Pro 14" M5, Apple Silicon (arm64), 16 GB RAM, macOS Tahoe 26.6.2
- Docker Desktop 29.8.0, running native arm64 images (no Rosetta required so far)
- Working directory: `~/iam-lab`

---

## Decisions

### Why Docker Compose rather than `docker run`

The first Keycloak instance was started with a single `docker run` command.
It worked, but the configuration lived only in shell history, the terminal was
blocked by the foreground process, and nothing described how the container
related to anything else.

Compose makes the environment declarative. The file is both the runtime
definition and the documentation, and it is what makes the lab reproducible by
a third party.

### Why PostgreSQL instead of the embedded database

`start-dev` uses an embedded H2 database inside the container. Removing the
container destroys every realm, user and group with it.

Moving to PostgreSQL with a named volume separates data from container
lifecycle. Containers can be destroyed and recreated at will.

Verified in the startup log: the installed feature set reports
`jdbc-postgresql` rather than `jdbc-h2`.

### Why a health check on the database

`depends_on` alone only waits for a container to start, not for the service
inside it to become usable. Keycloak would attempt to connect to a PostgreSQL
instance still initialising and fail.

`condition: service_healthy` combined with `pg_isready` makes the dependency
meaningful. Startup output confirms the database reaches `Healthy` before
Keycloak starts.

### Why the database port is not published

The PostgreSQL service exposes `5432/tcp` on the Compose network but publishes
nothing to the host. Keycloak reaches the database by service name over the
internal network; nothing outside the project can.

This mirrors production practice, where the datastore is never directly
reachable and only the application talks to it.

### Why the bootstrap admin was kept

Keycloak 26 treats `KC_BOOTSTRAP_ADMIN_*` as emergency credentials rather than
a permanent account — the startup log calls it a *temporary admin user*, and
the console requires a password change on first sign-in. The reasoning is
sound: a password set through an environment variable is visible in
`docker inspect`, in shell history, and frequently ends up committed.

Creating a named admin account by hand was considered and rejected. Anything
created manually in the `master` realm lives in the volume: a
`docker compose down -v` destroys it, and no file in the repository records
that it ever existed. It is operational state, not configuration, and adding it
buys nothing.

The reproducibility problem is better solved by exporting realm configuration
to JSON and version controlling it. If a named administrator is ever needed, it
belongs in an automated bootstrap step, not in a sequence of clicks.

### Why a separate realm rather than `master`

`master` administers the Keycloak server itself; an account there can manage
every other realm. Application populations never belong in it.

All Sigilla users, groups and roles live in the `sigilla` realm.

### Why the school name is fictional

Several candidate names were checked against real institutions and discarded:

- *Alpine International School* — at least three real schools in India
- *Tessera* — one character from Tessa International School, Hoboken NJ
- *Bifröst* — Bifröst University, Iceland
- *Sigillum* — generic in academic Latin; appears inside the seals of Harvard,
  Brown, Vanderbilt and others

*Sigilla* returned no institutional matches. A public repository containing
invented HR records should not carry the name of a real school.

### Why the schema was declared before any user existed

The four HR-derived attributes (`employeeNumber`, `department`, `jobTitle`,
`managerEmployeeNumber`) were added to the realm's User Profile before a single
account was created. Declaring an attribute after the fact leaves every
existing account with it empty, which is tedious for five users and a project
for five thousand.

All four are readable by the user but writable only by an administrator. They
originate from an authoritative source: if a user could edit their own
department, there would be two competing versions of the truth and the next
reconciliation would overwrite theirs anyway. Attributes derived from an
authoritative source are read-only in the target system.

`managerEmployeeNumber` references the manager by employee number rather than
by name or email, for the same reason correlation does. It carries no weight
yet, but an access certification campaign needs a reliable management chain,
so it belongs in the schema from the start.

### Why entitlements hang off groups, not users

Roles describe what can be done. Groups describe who someone is. midPoint will
manage group membership only, and never assign a role directly to an account.

The alternative — assigning roles per user — works, but answering "who can
approve payments?" then means walking every account. With entitlements on
groups, the answer is one screen. It also reduces provisioning to a single
operation: add to group, or remove from group.

Subgroups inherit their parent's roles, so `portal-access` is declared once on
`/staff` and reaches all staff. Repeating it across seven departments would be
seven places to forget.

### Why test accounts join leaf groups only

The first account was initially given both `/staff` and `/staff/academic`.
The parent membership was removed before saving.

It changes no access — `/staff/academic` already inherits everything from
`/staff` — but midPoint derives membership from the `department` field, which
yields the leaf group alone. A hand-made account carrying a membership the
policy would not produce shows up in reconciliation as drift, and the time lost
is spent debugging midPoint for a defect that lives in the test data.

Test data must mirror what the automation would produce, or it validates
nothing. The same reasoning applies to `emailVerified`, set consistently across
all three accounts.

### Reading the Inherited column

It answers a different question depending on where it is shown. On a group, it
means the role came from an ancestor group. On a user, it means the role was
not assigned directly to that person.

On all three test accounts, every business entitlement shows `Inherited: True`.
The only direct assignment is `default-roles-sigilla`, created by Keycloak
itself. Zero personal exceptions — every entitlement is traceable to a group.

---

## Verified

### Group inheritance

| Account | Groups | Effective entitlements |
|---|---|---|
| `cdubois` | `/staff/academic` | `portal-access`, `academic-records-read`, `academic-records-write` |
| `mrossi` | `/staff/academic`, `/responsibilities/residential-tutors` | the above plus `student-welfare-read` |
| `aweber` | `/staff/finance`, `/responsibilities/finance-approvers` | `portal-access`, `finance-read`, `finance-write`, `finance-approve` |

`mrossi` is the case the two-branch model exists for: a teacher who also serves
as a residential tutor. Dropping the tutoring role removes
`student-welfare-read` and leaves the academic entitlements untouched.

### Segregation of duties violation (intentional)

`aweber` holds `finance-write` and `finance-approve` simultaneously — she can
record an invoice and approve its payment. Keycloak granted both without
complaint, because it enforces policy rather than judging it.

Nothing on the screen indicates a problem: no warning, no flag. This is how SoD
violations survive for years in production, and it is the "before" state for
the detection work in midPoint.

---

## Open items

- [ ] Move `KC_BOOTSTRAP_ADMIN_*` to a `.env` file, commit a `.env.example`,
      add `.env` to `.gitignore`
- [ ] Add a health check to the Keycloak service using the management endpoint
      on port 9000 (already enabled via `KC_HEALTH_ENABLED`)
- [x] Export the `sigilla` realm to JSON and commit it —
      `keycloak/realm-sigilla.json`, includes the User Profile schema
- [ ] Remove the stopped container left over from the pre-Compose run
- [ ] Add validation rules to the custom attributes (e.g. `employeeNumber`
      matching `EMP\d{4}`)
- [ ] Build the HR CSV and stand up midPoint on port 8081
