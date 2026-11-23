---
name: rust-review
description: "Rust lane for a code review: idioms, types that make invalid states unrepresentable, error enums, visibility, cfg boundaries, and std or crate alternatives. Use for \"rust review\" or inside a broader review of .rs changes."
metadata:
  calls: ["rust-best-practices"]
---

# Rust Review

Review changed Rust code against the base branch for changes that make the code
more idiomatic, cleaner, and more functional without turning taste into noise.
Focus on actionable comments that improve API shape, visibility boundaries,
invariant enforcement, state modeling, ownership, error handling, and
readability.

## 1. Choose The Diff

If the user gives a PR number, branch, commit range, or patch, use that target.
Otherwise compare the current branch to the repository base branch:

```bash
git diff origin/master...HEAD
git diff origin/master...HEAD --stat
```

If that diff is empty or `origin/master` does not exist, try `origin/main...HEAD`,
`master...HEAD`, then `main...HEAD`. Review only changed Rust-relevant files:
`.rs`, `Cargo.toml`, `Cargo.lock`, build scripts, generated bindings when the
changed Rust code depends on them, and tests that exercise Rust behavior.

## 2. Load Context

Before commenting:

- Read the changed Rust files in full, not just the diff hunk.
- Read nearby public types, constructors, trait impls, tests, feature flags, and
  call sites needed to judge whether an idiom is actually appropriate here.
- Identify crate boundaries, public API stability, error type conventions,
  async runtime, serialization/deserialization constraints, and whether `no_std`,
  FFI, or performance constraints affect normal idioms.
- Map the module tree and call sites needed to decide the narrowest correct
  visibility for changed types, fields, constructors, methods, traits, modules,
  and re-exports. Distinguish stable public API from crate-internal API,
  test-only helpers, and private implementation details.
- Identify the relevant standard-library APIs, crate-local helper modules,
  enabled dependency features, and dependency policy before suggesting a new
  implementation shape or library.
- Identify test-only helpers and snapshot conventions already provided by the
  repository. Before reviewing changed test assertions, check whether a shared
  workspace crate exposes an `assertions` module (often behind a `test-utils`
  feature) and whether a snapshot crate such as `goldie` or `insta` is an
  established dev dependency.
- Identify assertions evaluated during compilation, including `assert!` in a
  const item or const block and helpers such as `const_assert!` or
  `const_assert_eq!`. Determine what each assertion protects and whether a
  focused unit test or a structural type/API constraint can replace it.
- Trace changed Cargo features and `cfg` predicates through the module tree,
  imports, re-exports, implementations, call sites, and tests. Determine whether
  each condition belongs on a whole module, a coherent item or implementation,
  or only a small local branch.
- Load `rust-best-practices` and read the handbook chapters that match the changed code: borrowing,
  Clippy policy, performance, errors, tests, dispatch, type state, docs,
  pointers. The repository's MSRV, lint setup and conventions win on conflict.
- Run formatting or tests only when the user asks for fixes or when the repo
  clearly documents a cheap Rust verification command.

## 3. Review Lens

Treat "idiomatic, cleaner, functional Rust" as practical engineering:

- **Idiomatic** means using Rust's type system, ownership, borrowing, `Result`,
  `Option`, traits, and module visibility in the way Rust callers expect.
  Examples: prefer `impl From<T>`/`TryFrom<T>` over ad hoc conversion helpers
  when it improves call sites; borrow `&str` instead of requiring `String` when
  ownership is not needed; use private, `pub(super)`, `pub(crate)`, or
  `pub(in path)` visibility when an item is not part of the external API; avoid
  `clone()` by reshaping ownership rather than fighting the borrow checker.
- **Cleaner** means smaller public surfaces, names that expose the domain, fewer
  invalid states, and less incidental control flow. Example: use a private-field
  newtype plus constructor so callers cannot build invalid values, such as
  `struct ShardCount(NonZeroU32);` with `TryFrom<u32>` instead of storing a raw
  `u32` that must be checked everywhere. Use enums when the domain has mutually
  exclusive states, especially when separate booleans or optional fields allow
  combinations the system should never represent.
- **Functional** means expressing data transformation and fallible flow directly
  with iterators, combinators, pattern matching, and `?` when that improves
  clarity. Examples: `items.iter().filter_map(parse).collect::<Result<Vec<_>, _>>()?`
  for a pipeline that naturally transforms data; `ok_or_else(...)?` when an
  absent value is an error. Do not force combinators when a `for` loop or
  `match` is clearer.
- **Library-backed** means asking whether custom changed logic should instead use
  `std`/`core`, a crate-local abstraction, an enabled feature from an existing
  dependency, a derive/proc macro already used in the crate, or a well-supported
  Rust crate. Suggest a new dependency only when it clearly removes meaningful
  domain complexity, duplicated validation, risky parsing/serialization,
  concurrency machinery, or long-term maintenance burden, and only after
  considering compile time, feature flags, `no_std`/FFI constraints, licensing,
  security posture, semver, and public API impact.

Look specifically for:

- Type invariants: public fields, primitive obsession, optional fields that
  create impossible combinations, constructors that permit invalid objects,
  missing `NonZero*`, range-bounded, non-empty, or state-specific types where the
  invariant is central to correctness.
- Enum and newtype modeling: related booleans, mode strings, flags, or
  `Option<T>` combinations that should be one enum; enum variants that should
  carry state-specific data; raw integers that should be `NonZeroU64`,
  `NonZeroUsize`, a crate-local `non_zero` type, or a private-field newtype with
  `TryFrom`/smart constructors. Prefer shapes that make invalid states
  unconstructable instead of relying on scattered runtime validation.
  For example, replace `enabled: bool` plus `rpc_enabled: bool` with an enum
  such as `Disabled | Enabled | WithRpc` when `rpc_enabled && !enabled` is
  invalid, and replace a raw `u64` that must never be zero with a `NonZeroU64`
  wrapper or domain newtype.
- API ergonomics: unnecessary ownership, awkward lifetimes, needless generics,
  missing trait impls (`Debug`, `Clone`, `Default`, `From`, `TryFrom`,
  `AsRef`/`Borrow` only when useful), and constructors that return the wrong
  error shape for existing crate conventions.
- Error modeling and handling: `unwrap`, `expect`, `panic!`, lost source errors,
  broad `anyhow` use in library boundaries, and missed `?` propagation. Prefer a
  dedicated error enum variant for each semantically distinct failure category
  that callers, tests, telemetry, or recovery logic may need to distinguish.
  Avoid `String` as the error type, catch-all variants such as
  `Error::Message(String)`, and repeated `map_err`/`format!` calls that encode
  error identity only in prose. Keep variable context in typed variant fields
  and preserve underlying causes with `source`/`#[source]`; derive or implement
  `Display` to produce the human-readable message. Do not demand a new variant
  for mere wording differences, or flag strings used only for presentation,
  logs, assertions, or application-boundary context when the underlying error
  remains typed.
- Control flow and data transformation: verbose `match`/`if let` chains that
  obscure intent, manual accumulation that should be `try_fold`, `collect`, or
  `filter_map`, and combinator-heavy code that should be simplified back into
  a readable loop.
- Ownership and allocation: avoidable clones, needless `String`/`Vec`
  allocation, taking owned values instead of references, returning references
  with brittle lifetimes, and interior mutability used to bypass ownership
  rather than model shared mutation.
- Existing API and dependency fit: handwritten parsing, validation,
  synchronization, serialization, bitflags, time handling, URL/path handling, or
  collection logic that could be clearer and safer through `std`/`core`,
  crate-local utilities, existing dependency features, or a justified new crate.
  Prefer reuse when it reduces real complexity; reject it when it hides simple
  code, expands the dependency surface for a marginal win, or conflicts with the
  crate's feature, licensing, security, or portability constraints.
- Visibility and API-surface hygiene: changed `pub` methods, associated
  functions, constructors, types, fields, enum variants, traits, modules,
  constants, test helpers, and re-exports that should be private, `pub(super)`,
  `pub(crate)`, or `pub(in path)` instead. Look for concrete implementation
  types leaked through public signatures, mutation hooks or constructors that
  bypass invariants, overly broad prelude exports, public modules used only by
  one parent/sibling module, and helper functions that should be private
  methods or associated constructors.
- Async and concurrency idioms: holding locks across `.await`, blocking calls in
  async contexts, unnecessary `Arc<Mutex<_>>`, missed `Send`/`Sync` implications,
  and cancellation-unfriendly loops.
- Compile-time assertion hygiene: flag changed assertions that run during normal
  compilation, including `const _: () = assert!(...)`, `const { assert!(...) }`,
  `static_assertions::const_assert!`, `const_assert_eq!`, and equivalent helpers.
  Prefer a focused `#[cfg(test)]` unit test that uses normal test assertions and
  names the behavior or invariant. This keeps test-only validation out of the
  production compilation path. Do not flag `assert!`, `assert_eq!`, or
  repository-native assertion macros merely because they appear inside a unit
  test. If a compile-time assertion protects an unsafe layout, ABI, or other
  invariant that a unit test cannot safely replace, still report it and ask for
  a repository-approved structural guarantee or explicit justification; do not
  silently weaken the safeguard.
- Test assertion and snapshot hygiene: in crates whose workspace provides a
  shared `assertions` module, prefer its repository-standard macros over direct
  `claims` imports, `.unwrap()`/`.expect()` extraction, boolean checks such as
  `assert!(result.is_ok())`, `assert!(result.is_err())`,
  `assert!(option.is_some())`, or `assert!(option.is_none())`, and manual
  `match`/`if let` blocks used only to fail and extract a value. Use
  `assert_ok!`, `assert_err!`, `assert_some!`, `assert_none!`, and
  `assert_matches!` as appropriate. Use `assert_err_matches!` when the test must
  verify an exact error variant or its fields; do not weaken that check to mere
  `is_err()`. Import these from the shared `assertions` module, and ensure the
  crate enables the shared crate with its test-utils feature under
  `[dev-dependencies]`. Use the repository's own names for these macros where
  they differ. Do not add a production `Debug` implementation for a
  secret or opaque type only to satisfy an assertion macro; use the narrowest
  repository-approved alternative when required trait bounds make the standard
  macro unsuitable.
- Snapshot coverage: when a changed test compares rendered, serialized, JSON,
  or debug output against an inline expected literal, replace the literal with
  the repository's established snapshot form, such as `goldie::assert!`,
  `goldie::assert_json!`, or `goldie::assert_debug_alt!` with Goldie, or the
  matching `insta` macro. Prefer the most
  structured snapshot form so diffs stay useful. Stabilize map ordering,
  timestamps, randomness, paths, and other nondeterministic inputs before
  recording the golden file; regenerate snapshots from the test instead of
  hand-editing them. Keep small scalar or enum assertions inline when the value
  itself is the behavior under test, and do not introduce a snapshot crate into
  a crate whose dependency policy does not permit it.
- Feature and `cfg`-gating hygiene: repeated `#[cfg(...)]` or
  `#[cfg_attr(...)]` predicates scattered across imports, types, impls,
  functions, and tests when one coherent boundary can express the condition.
  When an entire module or subtree shares a condition, prefer gating its `mod`
  declaration or the highest coherent module, impl, or item boundary. Consider
  feature- or platform-specific submodules when implementations diverge. Keep
  gates local when the surrounding module also contains unconditional API or
  when hoisting would change public API, documentation, test coverage, or build
  behavior. Check that Cargo features, optional dependencies, re-exports, call
  sites, and tests use aligned predicates so supported feature combinations do
  not leave missing items, stale imports, or dead branches. Hoisting one
  condition must not erase an independent condition such as `#[cfg(test)]` or a
  narrower target gate. When recommending a higher boundary, name the adjacent
  Cargo, dependency, re-export, caller, and test predicates that must remain
  aligned instead of treating the change as attribute removal alone. Note that
  `cfg!(...)` produces a boolean but still compiles both branches; use
  `#[cfg(...)]` when unavailable code or dependencies must be removed. Do not
  recommend `cfg_if!`, `cfg_attr`, or predicate aliases only to save a few lines;
  the replacement should make the compilation boundary easier to understand.
- Cargo and crate hygiene: feature flags, optional dependencies, default
  features, semver-sensitive public API changes, and lockfile churn that does
  not match dependency changes.

## 4. Calibrate Findings

Prefer comments that point to a changed line and include a concrete replacement
direction. Do not comment on every stylistic preference. A Rust idiom finding is
worth raising when it:

- Makes invalid states impossible or moves checks to the boundary.
- Replaces boolean flag combinations, nullable-field combinations, or raw
  primitives with enums/newtypes that encode the valid states directly.
- Simplifies callers or reduces duplicated validation.
- Replaces error strings or catch-all message variants with typed variants when
  distinct failure categories need programmatic handling or stable identity.
- Removes avoidable allocation, cloning, locking, or panic paths.
- Aligns with conventions already present in the crate.
- Replaces bespoke code with `std`/`core`, an existing dependency feature, or a
  justified library-backed approach that materially improves correctness,
  clarity, or maintainability.
- Narrows visibility in a way that protects invariants, avoids accidental semver
  commitments, or prevents crate-internal helpers from becoming part of the
  public surface.
- Consolidates repeated feature or target gates at a coherent module, impl, or
  item boundary without hiding unconditional code or changing supported API.
- Moves compile-time assertions into focused unit tests, or replaces them with a
  structural guarantee when the invariant must hold before code generation.
- Replaces ad hoc test result/option checks with the repository's shared
  assertion macros, or replaces snapshot-like expected literals with the
  established snapshot assertion, so failures expose the value and repository conventions do
  not drift.
- Improves public API clarity without causing excessive churn.

Downgrade or omit findings when the code is generated, compatibility requires
the current shape, the idiom would obscure simple logic, or the change is outside
the touched Rust surface.

## 5. Output

Return findings first. Use this shape:

```markdown
# Rust Review

**Scope:** [diff target]
**Rust files reviewed:** N

## Findings

### Must Fix
1. [path:line] Concrete issue, why it matters, and the smallest idiomatic fix.

### Suggestions
1. [path:line] Non-blocking improvement and why it is worth considering.

### Nits
1. [path:line] Small cleanup that is safe to ignore.

If a section has no findings, say so in one sentence.

## Idiom Summary
[2-4 sentences summarizing the main opportunities, or say the Rust is already
idiomatic for this diff.]
```

Severity guide:

- **Must Fix**: current code can construct invalid values, expose public
  constructors/fields/methods that bypass invariants, panic unexpectedly, break
  public contracts, lose errors, fail a supported feature/target configuration,
  or create material async/concurrency risk.
- **Suggestions**: code works, but a Rust-native type, visibility restriction,
  constructor, trait impl, iterator shape, ownership change, or cleaner
  conditional-compilation boundary would materially improve maintainability.
- **Nits**: naming, visibility, small call-site ergonomics, or local cleanup.

When the user asks for GitHub-ready comments, use lowercase prefixes:
`issue:`, `suggestion:`, and `nit:`. Keep each comment grounded in the changed
line and avoid broad essays about Rust style.
