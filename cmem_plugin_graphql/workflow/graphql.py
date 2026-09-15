"""GraphQL workflow plugin module"""

import json
from collections.abc import Iterator, Sequence
from typing import Any

import jinja2
import validators
from cmem_plugin_base.dataintegration.context import ExecutionContext, ExecutionReport
from cmem_plugin_base.dataintegration.description import Plugin, PluginParameter
from cmem_plugin_base.dataintegration.entity import Entities, EntitySchema
from cmem_plugin_base.dataintegration.parameter.multiline import (
    MultilineStringParameterType,
)
from cmem_plugin_base.dataintegration.parameter.password import Password, PasswordParameterType
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.ports import (
    FixedSchemaPort,
    UnknownSchemaPort,
)
from cmem_plugin_base.dataintegration.utils.entity_builder import build_entities_from_data
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import TransportConnectionFailed, TransportQueryError
from graphql import GraphQLError, GraphQLSyntaxError

from cmem_plugin_graphql.workflow.utils import (
    entities_from_payload,
    get_dict,
    is_jinja_template,
    output_schema_from_query,
)

# The schema of a run that sent no query at all and so has nothing to describe.
EMPTY_SCHEMA = EntitySchema(type_uri="", paths=[])


@Plugin(
    label="GraphQL query",
    description="Sends a GraphQL query or mutation to an endpoint and returns the result"
    " as entities.",
    documentation="""This task sends a GraphQL query or mutation to an endpoint and
captures the response.

Jinja syntax in the query or in the variables turns the task into a loop: both
are rendered once per arriving entity and the endpoint is called once per
entity, with a failing entity logged, counted in the report and skipped rather
than taking the whole task down. Text without Jinja syntax is sent exactly
once, and anything connected as input is then ignored.

The responses leave on the output port, one entity per call. Their paths are
the fields the query asks for, under the alias where a field has one, so the
next task is offered the schema while the workflow is drawn rather than only
after a first run. A field that selects sub fields becomes a relation, and the
entities behind it follow the shape of the response.

How many values a field carries is not part of a query - that lives in the
endpoint's own schema - so every path is offered as possibly multi valued and
the entities are built to match. A field the endpoint answers with a single
object therefore arrives as a list holding one entity, and a JSON dataset
connected to the output port holds an array in that place.

The task usually opens a chain: a GraphQL API at one end, and at the other a
transform that maps the response into a graph, or a dataset that keeps it for
later steps.

Three kinds of query describe nothing in advance, and the schema then stays
unknown until the task has run, which the next task has to accept as it comes:
one that does not parse as GraphQL on its own, which is the usual case for a
Jinja template because the placeholders sit where GraphQL expects values; one
holding more than one operation; and one whose top level is a fragment rather
than plain fields.

Jinja text is never checked for GraphQL syntax errors until it is rendered, so
a mistake in it surfaces while the task runs, as a failed entity, rather than
as a configuration error while it is set up. Two combinations go wrong quietly
in opposite ways when nothing is connected to the input: a Jinja-templated
query is sent with its `{{ ... }}` text unrendered and takes the task down,
while Jinja-templated variables send no query at all and the task completes as
though there had been nothing to do.
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
    # the order of the decorator, so Access token sits here to appear under Endpoint. It
    # carries no Python default because it precedes a parameter that has none; the
    # PluginParameter declares `default_value` instead, which is what makes it optional.
    def __init__(
        self,
        graphql_url: str,
        access_token: Password | str,
        graphql_query: str,
        graphql_variable_values: str = "",
    ) -> None:
        self.graphql_query: str = ""
        self.graphql_variable_values: str = ""
        self.jinja_query: bool = False
        self.jinja_variable_values: bool = False

        if not validators.url(graphql_url):
            raise ValueError("Provide a valid GraphQL URL.")

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
        """Validate and set graphql_query"""
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
        if (inputs and self.jinja_query) or self.jinja_variable_values:
            for entities in inputs:
                for result in self.process_entities(entities=entities):
                    if not result:
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

        summary: list[tuple[str, str]] = []
        warnings: list[str] = []
        summary.append(("Failed entities", str(failed_entities)))
        context.report.update(
            ExecutionReport(
                entity_count=processed_entities,
                operation="read" if self.graphql_query.startswith("query") else "write",
                operation_desc="entities processed",
                summary=summary,
                warnings=warnings,
            )
        )
        if self.output_schema:
            # The declared schema has to hold for whatever came back, so the entities are
            # built to match it rather than read off the response.
            return entities_from_payload(payload, self.output_schema)
        # An empty payload carries no shape to read a schema off, so build_entities_from_data
        # answers None rather than an empty collection.
        entities = build_entities_from_data(payload)
        if entities is None:
            return Entities(entities=iter([]), schema=EMPTY_SCHEMA)
        return entities

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

    def process_entities(self, entities: Entities) -> Iterator[dict[str, Any] | None]:
        """Process entities"""
        client = self._create_client()
        environment = jinja2.Environment(autoescape=True)
        for jinja_variable_values in get_dict(entities):
            result = None
            template = environment.from_string(self.graphql_query)
            query = template.render(jinja_variable_values)

            template = environment.from_string(self.graphql_variable_values)
            variable_values = template.render(jinja_variable_values)
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
                self.log.error(f"Failed entity: {type(ex)}")  # noqa: TRY400

            yield result

    def _set_ports(self) -> None:
        """Define input/output ports based on the configuration"""
        self.output_schema = output_schema_from_query(self.graphql_query)
        self.output_port = (
            FixedSchemaPort(schema=self.output_schema)
            if self.output_schema
            else UnknownSchemaPort()
        )
