"""GraphQL workflow plugin module"""

import json
from collections import OrderedDict
from collections.abc import Iterator, Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
from typing import Any

import validators
from cmem_plugin_base.dataintegration.context import ExecutionContext, ExecutionReport
from cmem_plugin_base.dataintegration.description import Plugin, PluginParameter
from cmem_plugin_base.dataintegration.entity import Entities, EntitySchema
from cmem_plugin_base.dataintegration.parameter.choice import ChoiceParameterType
from cmem_plugin_base.dataintegration.parameter.multiline import (
    MultilineStringParameterType,
)
from cmem_plugin_base.dataintegration.parameter.password import Password, PasswordParameterType
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.ports import (
    FixedNumberOfInputs,
    FixedSchemaPort,
    UnknownSchemaPort,
)
from cmem_plugin_base.dataintegration.typed_entities.file import FileEntitySchema, LocalFile
from cmem_plugin_base.dataintegration.utils.entity_builder import build_entities_from_data
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import TransportConnectionFailed, TransportQueryError
from graphql import GraphQLError, GraphQLSyntaxError
from graphql.language import OperationDefinitionNode

from cmem_plugin_graphql.workflow.utils import (
    entities_from_payload,
    get_dict,
    input_schema_from_templates,
    is_jinja_template,
    output_schema_from_query,
    render_template,
    without_dangling_relations,
)

# The schema of a run that sent no query at all and so has nothing to describe.
EMPTY_SCHEMA = EntitySchema(type_uri="", paths=[])

OUTPUT = SimpleNamespace()
OUTPUT.entities = "entities"
OUTPUT.file = "file"
OUTPUT.options = OrderedDict(
    {
        OUTPUT.entities: f"{OUTPUT.entities} - the responses as entities, to map or transform",
        OUTPUT.file: f"{OUTPUT.file} - the responses as one JSON file, to store or upload",
    }
)

# The name the written file carries. A response is not a file at the endpoint, so there is
# no name to take from it, and a temporary file's own name is noise in a later task.
RESULT_FILE_NAME = "graphql-result.json"


@Plugin(
    label="GraphQL query",
    # Set explicitly so the module path and the class name stop deciding it: while it was
    # generated, moving this module or renaming the class silently changed the identity of
    # every deployed task. The value is the `<package>-<Name>` form rather than the
    # generated `cmem_plugin_graphql-workflow-graphql-GraphQLPlugin`, which a task
    # configured before 7.0.0 still references - a release removing two parameters already
    # requires such a task to be reconfigured, so the identifier moves in the same step
    # rather than staying crooked for another major version.
    plugin_id="cmem_plugin_graphql-Query",
    description="Sends a GraphQL query or mutation to an endpoint and returns the result"
    " as entities.",
    documentation="""This task sends a GraphQL query or mutation to an endpoint and
captures the response.

## How often the endpoint is called

Jinja syntax in the query or in the variables turns the task into a loop: both are
rendered once per arriving entity and the endpoint is called once per entity, with a
failing entity logged, counted in the report and skipped rather than taking the whole
task down. Text without Jinja syntax is sent exactly once, and anything connected as
input is then ignored.

## What leaves the task

The responses leave on the output port in one of two shapes:

- **entities**: one per call. Their paths are the fields the query asks for, under the
  alias where a field has one, so the next task is offered the schema while the workflow
  is drawn rather than only after a first run. A field that selects sub fields becomes a
  relation, and the entities behind it follow the shape of the response.
- **file**: all responses of the run written to a single JSON file. What leaves the port
  is that one file rather than the data in it.

How many values a field carries is not part of a query - that lives in the endpoint's own
schema - so every path is offered as possibly multi valued and the entities are built to
match. A field the endpoint answers with a single object therefore arrives as a list
holding one entity, and a JSON dataset connected to the output port holds an array in
that place.

## Where this task fits

The task usually opens a chain: a GraphQL API at one end, and at the other a transform
that maps the response into a graph, or a dataset that keeps it for later steps. The file
shape suits the second kind of chain, and a task that uploads or stores what it is handed,
since a file travels through those without being taken apart on the way.

## Caveats

- **Three kinds of query describe nothing in advance**, and the entities then leave with a
  schema that stays unknown until the task has run, which the next task has to accept as
  it comes: one that does not parse as GraphQL on its own, which is the usual case for a
  Jinja template because the placeholders sit where GraphQL expects values; one holding
  more than one operation; and one whose top level is a fragment rather than plain fields.
  A run that hands on a file is not affected, since a file is described the same way
  whatever the query asks for.
- **Jinja text is never checked for GraphQL syntax errors until it is rendered**, so a
  mistake in it surfaces while the task runs, as a failed entity, rather than as a
  configuration error while the task is set up.
""",
    parameters=[
        PluginParameter(
            name="graphql_url",
            label="Endpoint",
            description="""The URL the query is sent to, for example
`https://fruits-api.netlify.app/graphql`.

A collective list of public GraphQL APIs is available
[here](https://github.com/IvanGoncharov/graphql-apis).
""",
        ),
        PluginParameter(
            name="access_token",
            label="Access token",
            description="""The token the endpoint is authenticated with. It is sent as the
`Authorization: Bearer <token>` header. Leave it empty for an endpoint that needs no
authentication.

For GitLab, a personal, project or group access token works, with scope
`read_api` for queries or `api` for mutations.
""",
            param_type=PasswordParameterType(),
            default_value="",
        ),
        PluginParameter(
            name="output_mode",
            label="Output mode",
            description="In which shape the responses leave this task.",
            param_type=ChoiceParameterType(OUTPUT.options),
            default_value=OUTPUT.entities,
        ),
        PluginParameter(
            name="graphql_query",
            label="Query",
            description="""The query or mutation to send, written in
[GraphQL](https://graphql.org/).

May contain Jinja syntax, for example `{{ id }}`, which is rendered against each
arriving entity before the query is sent.

```graphql
query allFruits {
  fruits {
    id
    scientific_name
    fruit_name
    family
    climatic_zone
  }
}
```
""",
            param_type=MultilineStringParameterType(),
        ),
        PluginParameter(
            name="graphql_variable_values",
            label="Query variables",
            description="""The values for the variables the query declares, as a JSON
object - `{"id": 1}` for a query taking `$id`. An empty object is sent for a query
that declares none.

May contain Jinja syntax, for example `{"id": {{ id }}}`, which is rendered against
each arriving entity before the query is sent.
""",
            default_value="{}",
            param_type=MultilineStringParameterType(),
        ),
    ],
)
class GraphQLPlugin(WorkflowPlugin):
    """GraphQL Workflow Plugin to query GraphQL APIs"""

    # DataIntegration renders the parameters in the order of this signature rather than
    # the order of the decorator, so Access token and Output mode sit here to appear
    # under Endpoint. Neither carries a Python default, because both precede a parameter
    # that has none; their PluginParameter declares `default_value` instead, which is
    # what DataIntegration reads and what keeps them optional.
    def __init__(
        self,
        graphql_url: str,
        access_token: Password | str,
        output_mode: str,
        graphql_query: str,
        graphql_variable_values: str = "",
    ) -> None:
        self.graphql_query: str = ""
        self.graphql_variable_values: str = ""
        self.jinja_query: bool = False
        self.jinja_variable_values: bool = False

        if not validators.url(graphql_url):
            raise ValueError("Provide a valid GraphQL URL.")

        if output_mode not in OUTPUT.options:
            raise ValueError(f"Provide a valid output mode: {', '.join(OUTPUT.options)}.")
        self.output_mode = output_mode

        self.graphql_url = graphql_url
        self.set_graphql_query(graphql_query)
        self.set_graphql_variable_values(graphql_variable_values)
        self.headers = {}
        token = access_token.decrypt() if isinstance(access_token, Password) else access_token
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

        self._set_ports()

    def set_graphql_variable_values(self, variable_values: str) -> None:
        """Validate and set graphql_variable_values"""
        try:
            if not variable_values:
                variable_values = "{}"
            variable_values = variable_values.strip()
            if is_jinja_template(variable_values):
                self.jinja_variable_values = True
            else:
                json.loads(variable_values)

            self.graphql_variable_values = variable_values
        except json.decoder.JSONDecodeError as ex:
            raise ValueError("Variables String is not valid.") from ex

    def set_graphql_query(self, query: str) -> None:
        """Validate and set graphql_query

        A template is not checked. It could be rendered with its placeholders standing
        in as `null` and the result parsed, but a template that supplies a field name
        or a whole selection renders to `null` in a position GraphQL needs a name in,
        so that check would reject configurations that are perfectly good.
        """
        query = query.strip()
        try:
            if is_jinja_template(query):
                self.jinja_query = True
            else:
                gql(query)

            self.graphql_query = query
        except GraphQLSyntaxError as ex:
            raise ValueError("Query string is not Valid.") from ex

    def execute(self, inputs: Sequence[Entities], context: ExecutionContext) -> Entities:
        """Execute GraphQL query"""
        self.log.info("Start GraphQL query.")
        processed_entities: int = 0
        failed_entities: int = 0
        payload = []
        per_entity = bool((inputs and self.jinja_query) or self.jinja_variable_values)
        if per_entity:
            for entities in inputs:
                for result in self.process_entities(entities=entities, context=context):
                    if result is None:
                        failed_entities += 1
                    else:
                        payload.append(result)
                        processed_entities += 1

                    context.report.update(
                        ExecutionReport(
                            entity_count=processed_entities + failed_entities,
                            operation="wait",
                            operation_desc="queries sent",
                        )
                    )

        else:
            client = self._create_client()
            request = gql(self.graphql_query)
            request.variable_values = json.loads(self.graphql_variable_values)
            result = client.execute(request)
            processed_entities += 1
            payload.append(result)

        summary: list[tuple[str, str]] = [("Failed entities", str(failed_entities))]
        warnings: list[str] = []
        if per_entity and not processed_entities and not failed_entities:
            # The run looked successful while doing nothing at all, which is how an input
            # that never arrives presents itself.
            warnings.append(
                f"Jinja syntax is configured, so the endpoint is queried once per arriving"
                f" entity - but nothing arrived on the input, and no query was sent."
                f" Received {len(inputs)} input collection(s)."
            )
        context.report.update(
            ExecutionReport(
                entity_count=processed_entities,
                operation=self._operation(),
                operation_desc="entities processed",
                summary=summary,
                warnings=warnings,
            )
        )
        if self.output_mode == OUTPUT.file:
            return self._result_file(payload)
        if self.output_schema:
            # The declared schema has to hold for whatever came back, so the entities are
            # built to match it rather than read off the response.
            return entities_from_payload(payload, self.output_schema)
        # An empty payload carries no shape to read a schema off, so build_entities_from_data
        # answers None rather than an empty collection.
        entities = build_entities_from_data(payload)
        if entities is None:
            return Entities(entities=iter([]), schema=EMPTY_SCHEMA)
        # Nothing was declared here, but the placeholder a null object leaves behind breaks
        # a dataset sink just the same, and a Jinja query always takes this branch.
        return without_dangling_relations(entities)

    def _operation(self) -> str:
        """Report whether this run reads or writes, as the execution report shows it

        The operation is in the parsed query, not in how the text happens to start:
        the anonymous shorthand `{ fruit { id } }` is a query, and reading the first
        word calls it a write. A template that does not parse keeps the guess, since
        there is nothing else to go on before it is rendered.
        """
        with suppress(GraphQLError):
            operations = [
                _
                for _ in gql(self.graphql_query).document.definitions
                if isinstance(_, OperationDefinitionNode)
            ]
            if len(operations) == 1:
                return "read" if operations[0].operation.value == "query" else "write"
        return "read" if self.graphql_query.startswith("query") else "write"

    def _result_file(self, payload: list[dict[str, Any]]) -> Entities:
        """Write the collected responses to one JSON file and hand it on as a file entity

        The file is written into a directory of its own so it can carry a name that says
        what it holds, and `ensure_ascii` stays off so a response with non-ASCII text
        reaches the file as that text rather than as escape sequences.
        """
        path = Path(mkdtemp(prefix="cmem-plugin-graphql-")) / RESULT_FILE_NAME
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.log.info(f"Wrote the responses to {path}.")
        schema = FileEntitySchema()
        file = LocalFile(path=str(path), mime="application/json")
        return Entities(entities=iter([schema.to_entity(file)]), schema=schema)

    def _create_client(self) -> Client:
        """Create a GraphQL client for the configured endpoint

        `input_value_deprecation` is switched off because gql 4 requests deprecated input
        fields during introspection by default, which servers running an older graphql-js
        reject with `Unknown argument "includeDeprecated"`.
        """
        # Select your transport with a defined url endpoint
        transport = AIOHTTPTransport(url=self.graphql_url, headers=self.headers)
        # Create a GraphQL client using the defined transport
        return Client(
            transport=transport,
            fetch_schema_from_transport=True,
            introspection_args={"input_value_deprecation": False},
        )

    def process_entities(
        self, entities: Entities, context: ExecutionContext | None = None
    ) -> Iterator[dict[str, Any] | None]:
        """Process entities"""
        client = self._create_client()
        for jinja_variable_values in get_dict(entities):
            if context and self._is_canceled(context):
                self.log.info("Canceled, no further queries are sent.")
                break
            result = None
            query = render_template(self.graphql_query, jinja_variable_values)
            variable_values = render_template(self.graphql_variable_values, jinja_variable_values)
            try:
                request = gql(query)
                request.variable_values = json.loads(variable_values)
                result = client.execute(request)
            except (
                GraphQLError,
                GraphQLSyntaxError,
                TransportQueryError,
                TransportConnectionFailed,
                json.decoder.JSONDecodeError,
            ) as ex:
                # The message names what was wrong with this entity; the class alone does
                # not, and a run of thousands of entities is unreadable without it.
                self.log.error(f"Failed entity: {type(ex).__name__}: {ex}")  # noqa: TRY400

            yield result

    @staticmethod
    def _is_canceled(context: ExecutionContext) -> bool:
        """Report whether the user has asked the workflow to stop

        `context.workflow` is absent in some contexts, the test ones among them, so the
        access is guarded rather than assumed.
        """
        with suppress(AttributeError):
            return bool(context.workflow.status() == "Canceling")
        return False

    def _set_ports(self) -> None:
        """Define input/output ports based on the configuration

        The task declared no input port at all until now, so a dataset wired into it
        was never read: the per entity loop ran over nothing and the task reported a
        successful run of zero queries.

        A port is declared exactly when the task reads one - when the query or the
        variables carry Jinja syntax. Without it the task sends its text once and
        ignores anything connected, so a handle there would only invite a connection
        that does nothing.

        The port names the paths the templates ask for, rather than leaving the schema
        unknown. DataIntegration reads only the paths the consuming task requests, so a
        port naming none is handed nothing - which is the same empty run, declared.
        """
        input_schema = input_schema_from_templates(self.graphql_query, self.graphql_variable_values)
        self.input_ports = (
            FixedNumberOfInputs([FixedSchemaPort(schema=input_schema)])
            if input_schema
            else FixedNumberOfInputs([])
        )
        self.output_schema = output_schema_from_query(self.graphql_query)
        if self.output_mode == OUTPUT.file:
            self.output_port = FixedSchemaPort(schema=FileEntitySchema())
            return
        self.output_port = (
            FixedSchemaPort(schema=self.output_schema)
            if self.output_schema
            else UnknownSchemaPort()
        )
