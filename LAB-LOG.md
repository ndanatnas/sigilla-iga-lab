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

## The HR source

Sixteen records covering every department, with a management chain that
terminates at a director whose `managerEmployeeNumber` is empty — the edge case
that breaks naive rules.

The first three records reproduce the hand-made Keycloak accounts exactly, so
the first reconciliation has to correlate and link them rather than create
duplicates. One record carries a past `endDate` as the leaver case.

### A gap found while building it

The original schema had `isResidentialTutor` and `isHeadOfDepartment` but
nothing expressing "this person approves payments". The consequence would have
been severe: `aweber` sits in `/responsibilities/finance-approvers` in Keycloak,
but no rule derived from the CSV could produce that membership. Reconciliation
would have read it as drift and removed it — erasing the very SoD violation the
lab exists to demonstrate.

`isFinanceApprover` was added. The principle: every membership present in the
target must be derivable from policy. If it is not, it is either genuine drift
to be removed, or a gap in the model.

A second violation was then planted deliberately. `EMP0011`, Head of Finance and
`aweber`'s own manager, is also a finance approver. A detection rule that only
catches the first case would miss it, and in practice a conflict at management
level is the more serious finding.

### Derivation rules to implement

```
department               -> /staff/{department}
isHeadOfDepartment=true  -> /responsibilities/heads-of-department
isResidentialTutor=true  -> /responsibilities/residential-tutors
isFinanceApprover=true   -> /responsibilities/finance-approvers
endDate in the past      -> account disabled, all memberships revoked
```

### A deliberate simplification

`Kovac` is written without its diacritic. Accented characters in CSV raise real
encoding questions, but here they would only add a debugging variable that
teaches nothing about IGA. Worth revisiting later.

---

## Standing up midPoint

### Why one compose file rather than two

Evolveum's compose declares its own bridge network. Containers on different
networks cannot reach each other, so midPoint would have had no route to
Keycloak — and Keycloak is the target the whole lab depends on.

The alternative was an external shared network, which works but introduces
start-up ordering between two files. Merging into one file keeps the README's
promise of a single `docker compose up -d`, and reflects the reality that
Keycloak without midPoint demonstrates nothing, and the reverse is equally true.

With the network section removed entirely, every service lands on the project
default network and resolves the others by service name. From inside midPoint,
Keycloak is `http://keycloak:8080` — not `localhost:8080`, which inside a
container means the container itself.

### Other changes to Evolveum's file

- Port published as `8081:8080`; 8080 on the host belongs to Keycloak
- Image pinned to `4.9-alpine` instead of `${MP_VER:-latest}`, so the
  configuration and the version it was written for stay together
- `version: "3.3"` removed — obsolete and ignored by current Compose
- Health check added to the midPoint database; the original waited only for the
  container to start, not for Postgres to accept connections
- HR source bind-mounted read-only at `/hr-source`. An authoritative source is
  read, never written to by its consumer

The `midpoint-init` container was kept verbatim. It runs `ninja.sh -B info`
against the database and creates the schema only if that query fails — check
before acting, so a second run is harmless. It creates two schemas, REPOSITORY
and AUDIT, because audit data has its own retention requirements and must not be
affected by ordinary operations. midPoint itself waits on
`condition: service_completed_successfully`: a task container succeeds by
exiting, not by staying up.

### Architecture

`docker manifest inspect` confirmed `evolveum/midpoint:4.9-alpine` publishes
both amd64 and arm64. It runs natively on Apple Silicon; no Rosetta, no
`platform: linux/amd64`.

### Notes for whoever runs this

- midPoint serves under a context path: **http://localhost:8081/midpoint**.
  The bare host and port returns 404.
- Since 4.8.1 there is no default password. One is generated on first start and
  written to the log: `docker compose logs midpoint | grep -i password`.
- Startup logs several `PolicyType ... was not found` errors during initial
  import. `030-role-superuser.xml` is imported before
  `300-classification-privileged-access.xml`, which creates the referenced
  object. The closing line reports 147 objects, 0 errors.

### What the startup log confirms

- `ConnId com.evolveum.polygon.connector.csv.CsvConnector v2.8` is registered
  and will read the HR source
- `objectCollection ...353 (Users with SoD violations)` ships with midPoint, so
  the exclusion rule between `finance-write` and `finance-approve` will populate
  a ready-made screen rather than needing one built

---

## Open items

- [ ] Move `KC_BOOTSTRAP_ADMIN_*` and both database passwords to a `.env` file,
      commit a `.env.example`, add `.env` to `.gitignore`
- [ ] Add a health check to the Keycloak service using the management endpoint
      on port 9000 (already enabled via `KC_HEALTH_ENABLED`)
- [x] Export the `sigilla` realm to JSON and commit it —
      `keycloak/realm-sigilla.json`, includes the User Profile schema
- [ ] Remove the stopped container left over from the pre-Compose run
- [ ] Add validation rules to the custom attributes (e.g. `employeeNumber`
      matching `EMP\d{4}`)
- [x] Build the HR CSV and stand up midPoint on port 8081
- [ ] Configure the CSV resource and correlate on `employeeNumber`
- [ ] Configure the Keycloak resource as a provisioning target
- [ ] Implement the derivation rules and the joiner / mover / leaver flows
- [ ] Add the exclusion rule between `finance-write` and `finance-approve`
- [ ] Export midPoint objects to XML and version them alongside the realm
