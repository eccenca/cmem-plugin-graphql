<!-- markdownlint-disable MD012 MD013 MD024 MD033 -->
# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/) and this project adheres to [Semantic Versioning](https://semver.org/)

## [Unreleased]

### Added

- New **Access token** parameter, which holds the token encrypted instead of in plain text
  and is sent as the `Authorization: Bearer <token>` header - a GitLab personal, project or
  group access token works with it
- New **Output mode** parameter choosing the shape the responses leave in: `entities`, the
  default and what the task did so far, or `file`, which writes all responses of the run
  to one JSON file and hands that file on instead. The file shape suits a chain that
  stores or uploads the result rather than mapping it

### Changed

- Updated to cmem-plugin-template v9.7.0 and refreshed all dependencies
- The result always leaves on the output port now, one entity per query execution
- The plugin identifier is set explicitly now, so the module path and the class name stop
  deciding it and can move without orphaning the workflow tasks built on this one
- The output schema is derived from **Query** wherever the query describes its own
  response, so the paths are offered to the next task while the workflow is drawn
  instead of only becoming known once the task has run. A query that does not parse
  as GraphQL on its own - which a Jinja template usually does not - one holding
  several operations, and one whose top level is a fragment still offer an unknown
  schema. Because a query does not say how many values a field carries, every path
  is offered as possibly multi valued, and the entities are built to match that,
  so a field answering with a single object arrives as a one element list. A JSON
  dataset connected to the output port therefore holds an array wherever the
  endpoint answered with one object

- Reworked the task and parameter documentation for the reshaped task: it describes what
  leaves on the output port and how the schema follows from the query, says where the task
  sits in a chain, and keeps the caveat that Jinja text is only checked when it is
  rendered. It is now structured under headings, with
  the caveats as a list, so a reader can find one section without reading the rest. The
  **Endpoint**, **Query** and **Query variables** descriptions lead with what the
  parameter controls, and the query example renders as a code block

### Fixed

- A field the endpoint answers with null for some items and with an object for others
  no longer breaks a JSON dataset connected to the output port. Such a field was
  described as a relation and given an empty string instead of a reference where the
  answer was null, and the write failed with *Current context not Array but Object*
- The same null-object repair now covers a query carrying Jinja syntax, which describes
  no schema and therefore leaves through the other branch of the task. That branch handed
  the placeholder on untouched, so the per entity mode - the one the fault was found in -
  still failed the write
- Jinja values are no longer HTML escaped on their way into the query and the variables.
  A name such as `O'Brien & Co` reached the endpoint as `O&#39;Brien &amp; Co`, so a query
  asked about, and a mutation stored, a string nobody typed
- A failing entity is logged with the message of the error rather than only its class, so
  a run of many entities says which one failed and why
- A cancelled workflow stops the task between entities instead of querying the endpoint
  once for every remaining one
- A field the endpoint answers with text in one record and with an object in another no
  longer takes the task down with a bare `AttributeError` from inside a library. It still
  fails, because such a response cannot become entities, but the message names the field
  and says what to do instead
- A field selected twice at the top level of a query, which GraphQL merges into one key,
  is described once rather than twice and its objects are built once
- The objects behind one path are built across the whole run rather than per response, so
  a path answered with an object in one response and with null in another is described
  once instead of twice, contradictorily
- A value that is not text keeps its JSON form: `true`, `null` and `{"major": 1}` rather
  than Python's `True`, `None` and `{'major': 1}`
- Root entities carry an identifier of their own per run, so two runs, or two of these
  tasks in one workflow, no longer hand out the same ones
- An empty response object counts as a result rather than as a failed entity
- The execution report calls an anonymous `{ ... }` query a read, where it used to call
  anything not starting with the word `query` a write
- The task no longer talks to Corporate Memory at all

### Breaking Change

- The plugin identifier changed from `cmem_plugin_graphql-workflow-graphql-GraphQLPlugin`,
  which it generated from the module path and the class name, to `cmem_plugin_graphql-Query`.
  A task configured before this release stops resolving and its workflow fails with
  *Invalid plugin cmem_plugin_graphql-workflow-graphql-GraphQLPlugin* until the task names
  the new identifier. Rebuilding the task in the workspace works; so does rewriting the
  `type` of the existing task, which keeps its id, its place in every workflow, its
  parameter templates and its stored token
- The **Target JSON Dataset** parameter is gone. A task configured with one has to be rebuilt:
  connect the output port to the task that should receive the result, and write it to
  a dataset with a dedicated task where that is still wanted
- The **OAuth access token** parameter is gone. Move the value to **Access token**, which
  keeps it encrypted, and rotate the token, since everything stored in the old parameter
  was kept in plain text in the task configuration and in every project export


## [6.0.1] 2026-09-08

### Changed

- Expanded task and parameter documentation to describe port/value shapes and the Jinja
  templating edge cases around missing input

### Fixed

- GraphQL query plugin no longer converts non-ASCII characters to unicode escape sequences in
  the JSON written to the target dataset
- Fixed a related upload bug this uncovered: the target dataset write passed a text stream to
  an API that expects a byte stream, which silently truncated the uploaded file whenever the
  JSON contained multi-byte UTF-8 characters (masked previously only because escaped output
  was always pure ASCII)
- Query variables parameter description no longer renders its example as an indented code
  block due to leftover indentation in the source string

## [6.0.0] 2026-09-02

### Changed

- Update dependencies and template
- Upgrade to `gql` 4, and reduce its extras to `aiohttp`, the only transport this plugin uses

### Fixed

- A GraphQL endpoint which fails or is unreachable now fails the single entity and is
  counted in the "Failed entities" report, instead of aborting the whole task

### Breaking Change

- The TLS certificate of the queried GraphQL endpoint is now verified. Up to and including
  5.1.0, certificates were not checked at all, so a task pointing at an endpoint with a
  self-signed or otherwise untrusted certificate will now fail. Provide the endpoint with a
  certificate from a trusted authority.


## [5.1.0] 2026-08-05

### Changed

- Update dependencies and template
- Replace `cmem-cmempy` with `cmem-client`


## [5.0.0] 2024-10-16

### Changed

- Update of dependencies and template
- validation of python 3.13 compatibility

### Breaking Change

- Requires python 3.13 now (>= CMEM 25.3.x)


## [4.0.3] 2025-07.03

### Changed

- update dependencies validators to 0.35.0


## [4.0.2] 2025-07-03

### Changed

- upgrade template (cmem-plugin-base 4.12.1)
- upgrade gql to 3.5.3
 

## [4.0.1] 2025-05-05

### Changed

- update dependencies to mitigate critical h11 vulnerability CVE-2025-43859


## [4.0.0] 2024-10-03

### Changed

- upgrade template to 7.0.0
- generate entites from json payload
- set output port based on Target JSON dataset field value


## [3.1.0] 2023-10-24

### Changed

- upgrade template to 5.3.3
- upgrade gql to 3.5.0b6


## [3.0.0] 2023-07-11

### Changed

- upgrade template to 5.0.1 (python 3.11, CMEM 23.2, cmem-plugin-base 5)


## [2.0.1] 2022-08-26

### Changed

- description


## [2.0.0] 2022-07-26

### Changed

- adapt plugin execute method to ExecutionContext 


## [1.0.0] 2022-06-16

### Added

- initial version to query GraphQL API's

