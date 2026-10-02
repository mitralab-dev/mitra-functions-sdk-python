# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- `create_client()` without arguments now works inside a Server Function: the environment also accepts `MITRA_BASE_URL` (without the trailing `/legacy`), `MITRA_TOKEN` and `MITRA_PROJECT_ID`, which the Functions runtime injects. `MITRA_API_URL`, `MITRA_PLATFORM_ACCESS_TOKEN` and `MITRA_APP_ID` keep precedence.

## [0.1.0] - 2026-08-15

### Added

- Synchronous Python client for the Mitra Server Functions runtime.
- Authenticated profile access, entity CRUD, custom queries, function invocation, and integrations.
- Environment-based runtime configuration and explicit dependency injection for tests.
- Commit- and digest-pinned SDK parity fixture with exhaustive consumer and immutable-source gates.
