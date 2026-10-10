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

## The CSV resource

### Read-only was the right principle and the wrong configuration

The HR source was first bind-mounted `:ro`, on the reasoning that an
authoritative source is read by its consumers and never written to. The
connector refused:

```
Configuration error: Can't write to file '/hr-source/staff.csv'
```

Not *read* — *write*. The ConnId CSV connector requires write access to the file
and its directory even when the resource is source-only, because it creates a
lock file alongside the data to prevent concurrent reads during synchronisation,
and uses temporary files in the same directory during sync.

The `:ro` flag was dropped. The lesson is worth more than the fix: an
architectural intention has to fit what the tool actually supports. The tightest
access model on paper is worthless if the connector cannot operate under it —
either the restriction is relaxed, or it is enforced in another layer, for
instance by keeping the canonical file elsewhere and copying it into the
connector's directory.

### Paths inside a container are not paths on the host

The connector is configured with `/hr-source/staff.csv`, not
`/Users/.../iam-lab/hr-source/staff.csv`. The bind mount makes the same file
reachable under two different addresses depending on who is asking.

This is the same class of mistake as reaching Keycloak on `localhost:8080` from
inside the midPoint container, where `localhost` means the container itself.
Both cost hours to anyone who has not internalised that a container has its own
view of the world.

### Correlation and naming

`employeeNumber` was selected as **both** the unique attribute and the name
attribute.

Unique is the correlation key, for the reasons already recorded. Name is how the
account is displayed in listings and reports, and the temptation is to use
`email` because it reads better. That temptation reintroduces the problem
through the side door: in several configurations the name ends up serving as a
secondary identifier, and it is not stable across a change of surname.

`EMP0001` is less readable than `claire.dubois@sigilla.ch` in a list. The
midPoint User object carries the full name anyway; the resource screen is about
the account, not the identity. Readability is a convenience, stability is a
correctness property.

The password attribute was left unset. An authoritative HR feed carries no
credentials.

### Built from scratch rather than from a template

The wizard offers Inherit Template, Copy From Template and From Scratch. A
template would have produced a working resource with prefilled mappings and no
understanding of why they are what they are, and debugging someone else's
configuration is worse than writing your own. The CSV connector is the simplest
one there is — a text file with columns — so if any resource is worth building
by hand to learn the model, it is this one. The Keycloak resource will be
considerably more involved, and this experience pays for itself there.

### Left in Proposed (simulation)

A resource in *proposed* state can be queried but executes nothing: tasks run in
simulation and report what would have happened. Only *active* makes operations
real.

In production this is what stands between a mapping error and thousands of
revoked legitimate entitlements on first reconciliation. Simulate, read the
report, correct, then activate — the simulation is part of configuring a
resource, not an optional extra.

Superseded on 10 October 2026: moved to `active` after the simulated import ran clean.
See "The import pipeline" below.

### Verified

`Resource objects` lists all sixteen accounts, `EMP0001` through `EMP0020`. The
whole path is proven: file mounted into the container, connector reading it,
delimiter inferred correctly, `employeeNumber` serving as the identifier.

---

## The import pipeline

### An activation inbound that resolved to nothing

The first simulated import failed on all sixteen records while the task itself
reported success. Status "Finished", zero seconds, green. Added objects: 0.

Had it run in Full mode, the task would have reported success and created
nothing. The task succeeded; its work failed. Most provisioning incidents live
in that gap.

    IllegalArgumentException: Cannot determine definition from content for
    IDI null + null -> null
        at ItemDeltaItem.determineDefinition
        at MappingParser.parseSource
        at AbstractMappingImpl.evaluateTimeValidity
        at FullInboundsProcessing$SpecialInboundsEvaluatorImpl
             .evaluateSpecialInbounds

Three frames carry the answer. `evaluateSpecialInbounds` means the failure is
in an activation or credentials mapping, not in the seven attribute mappings.
`evaluateTimeValidity` narrows it to validFrom and validTo. `parseSource`
failing in `determineDefinition` means the mapping's source resolved to no
defined item.

The null is not a null value. It is a null definition. midPoint never read
anyone's data, which is why all sixteen failed identically.

The configuration said:

    <activation>
      <validFrom>
        <inbound>
          <source><path>startDate</path></source>

A bare `startDate` resolves to nothing. Resource attributes live under
`attributes/` on the shadow and carry the resource namespace. The attribute
mappings worked because their `<attribute><ref>ri:jobTitle</ref></attribute>`
wrapper supplies the definition. The activation block has no such wrapper.

Fixed by reusing the pattern already proven in the same file rather than
debugging the special inbound syntax:

    <attribute>
      <ref>ri:startDate</ref>
      <inbound>
        <strength>strong</strength>
        <target><path>activation/validFrom</path></target>
      </inbound>
    </attribute>

No date conversion expression was needed. The CSV carries `2021-08-15` and
midPoint converted it to xsd:dateTime on its own.

### Resource objects are not accounts

"Resource objects" reads live from the connector and shows what exists in the
source. "Accounts" lists shadows, midPoint's local record of those objects.

Why the shadow exists: it is what lets midPoint know an object was there after
it disappears from the source. No shadow means no deletion detection, and no
deletion detection means no deprovisioning.

### Versioning definition, not history

The simulation task exported at 66 KB. A task that had never run exported at
121 lines. The difference is execution state: operation result trees, counters,
timestamps.

Rule: version the definition, not the history. Stating it exposed it as
unenforced, since the files about to be committed were the large ones.

`tools/strip-task-state.py` removes the runtime blocks (`activityState`,
`operationStats`, `result`, `affectedObjects`, `_metadata`) and the per-run
timestamps and states.

    task-hr-source-import-simulation.xml   1338 -> 112 lines
    task-hr-source-import-full.xml          273 -> 129 lines

It parses the XML after cutting and refuses to write if malformed. `<result>`
is a nested structure, and a regular expression matching too greedily would
have produced a file that looked plausible and was not. A stripper that can
silently corrupt its input is worse than no stripper.

Well-formed is not intact, so the definitions were verified separately: name,
work block, kind and intent, and the documentation field all survived. The
documentation is the part most worth versioning, because it holds the
reasoning.

### The wizard decides when you are allowed to decide

Creating an import task with "Simulate task" switched OFF removes the Execution
step from the wizard entirely. No mode selector, no configuration selector.

The resulting task had no `<execution>` element at all. Its mode and
configuration scope appeared only under `<affectedObjects>`:

    <executionMode>full</executionMode>
    <predefinedConfigurationToUse>production</predefinedConfigurationToUse>

`<affectedObjects>` is a computed summary, not declared configuration. It is
midPoint saying "given current defaults, this is what would happen". A
prediction, not an instruction. Which means the defaults can be overridden.

### Experiment: does `proposed` block execution, or only hide configuration?

Hypothesis: a resource in lifecycle state `proposed` is an execution barrier in
its own right.

Method: declare `<mode>full</mode>` with
`<configurationToUse><predefined>development</predefined></configurationToUse>`
and run against the resource while still `proposed`. Syntax taken from the
simulation task midPoint generated itself, rather than written from memory.
Second time that method was used here. When the syntax is unknown, find an
instance the tool produced.

Predicted: 16 items processed, 0 created. Confidence about 7 in 10.

Result: the task failed after ten milliseconds with progress 0, and midPoint
suspended it.

    ConfigurationException: Full execution mode requires the use of
    production configuration
        at ActivityExecutionModeDefinition.getTaskExecutionMode
        at LocalActivityRun.getTaskExecutionMode
        at LocalActivityRun.runInternal

Rejected in the activity definition, before the first object is read.

So neither option the question offered. The two protections are not independent
gates that happen to overlap. They are one enforced invariant:

1. Full execution mode requires production configuration. Enforced, not
   conventional.
2. Production configuration does not see a resource in `proposed`.
3. Therefore a `proposed` resource cannot be touched in full mode. Not "should
   not be". Cannot.

There is no path where someone writes to production against half-finished
configuration, because the combination that would allow it does not validate.

The suspension is deliberate too. A misconfigured task stops and waits for a
human instead of rescheduling and filling the log with the same error.

Prediction scored: right direction, wrong mechanism. I expected the writes to
be discarded after processing. In fact the task never starts.

Method note: the outcome table had three rows and reality supplied a fourth.
Enumerating outcomes before an experiment is worth doing, and the list is never
complete.

### Moved to Active

Lifecycle state changed from `proposed` to `active` on 10 October 2026. The
deliberate act of declaring the configuration operational. Until then it was a
draft that could be exercised but not applied.

### First real import

Task restored to its defaults (no `<execution>` block, so full plus
production), resumed, and run.

    resultStatus      success
    progress          16
    totalSuccessCount 32
    totalFailureCount 0

Sixteen rows processed, thirty-two object operations: sixteen users created and
sixteen shadows updated to point at them. User count went from 1 to 17.

**EMP0009, Nina Petrova, was created disabled.** Her contract ended 2026-08-31
and her row is still in the HR file. midPoint read the endDate, set validTo,
computed the effective status, and created her account without access. No
ticket, no human noticing, no cleanup step.

A feed copies data. A governance pipeline applies the rule, including to the
records nobody tidied up.

### Configuration drift, in the opposite direction

Until this point the entire midPoint configuration lived in one place: the
container's PostgreSQL. The repository held the compose file and the CSV, and
none of the identity configuration.

Same failure as the `:ro` mount, inverted. There the declarative source was
wrong and the running system right. Here the running system was right and the
declarative source did not exist. Both are the same mistake: treating the
running environment as the source of truth.

### Operational note

`curl -s` without `-f` treats an HTTP error as success. A mistyped password
returned 401 with an empty body, curl wrote a zero-byte file and exited 0, and
the `&&` chain deleted the backup.

Correct pattern for anything that replaces a file from the network: write to a
temporary file, verify the content, then move into place.

    TMP=$(mktemp) && curl -sf ... -o "$TMP" \
      && test -s "$TMP" && grep -q 'expected' "$TMP" \
      && mv "$TMP" target.xml


## Open items

- [ ] Move `KC_BOOTSTRAP_ADMIN_*` and both database passwords to a `.env` file,
      commit a `.env.example`, add `.env` to `.gitignore`
- [ ] Add `hr-source/.*.lock` to `.gitignore` — the CSV connector writes a lock
      file next to the data
- [ ] Add a health check to the Keycloak service using the management endpoint
      on port 9000 (already enabled via `KC_HEALTH_ENABLED`)
- [x] Export the `sigilla` realm to JSON and commit it —
      `keycloak/realm-sigilla.json`, includes the User Profile schema
- [ ] Remove the stopped container left over from the pre-Compose run
- [ ] Add validation rules to the custom attributes (e.g. `employeeNumber`
      matching `EMP\d{4}`)
- [x] Build the HR CSV and stand up midPoint on port 8081
- [x] Create the CSV resource, correlating and naming on `employeeNumber`
- [x] Configure attribute mappings from the CSV into midPoint User objects
- [ ] Configure the Keycloak resource as a provisioning target
- [ ] Implement the derivation rules and the joiner / mover / leaver flows
- [ ] Add the exclusion rule between `finance-write` and `finance-approve`
- [x] Export midPoint objects to XML and version them alongside the realm
- [ ] Create a service account with a declared human owner and a
      time-limited credential, and include it in a certification campaign
- [ ] Deactivate the owner of a service account and observe what happens
      to it (Evolveum documents no mechanism preventing orphaning)
