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

An input port accepts entities, but it only changes anything when **Query** or
**Query variables** actually contains Jinja syntax: the query and variables are
then rendered once per input entity and the endpoint is called once per entity,
with a failed entity logged and skipped rather than failing the whole task. A
purely static query and variables text runs exactly once and ignores any
connected input entirely.

The collected responses leave on the output port, one entity per query
execution. The fields a response carries are the fields **Query** asks for, so
the output schema is known before the endpoint is called and is offered to the
next task while the workflow is drawn: each field selected at the top level of
the query becomes a path, under its alias where it has one, and a field that
selects sub fields becomes a relation whose own paths follow from the response.

How *many* values a field carries is not part of the query - it is in the
endpoint's own schema - so every path is offered as possibly multi valued, even
where the endpoint only ever answers with one.

Three kinds of query describe no schema in advance, and the task then offers an
unknown one instead, which a downstream task has to accept as it comes: a
**Query** that does not parse as GraphQL on its own, which is the usual case
for a Jinja template because the placeholders sit where GraphQL expects values;
a query holding more than one operation; and one whose top level is a fragment
rather than plain fields.

A Jinja-templated **Query** or **Query variables** is never checked for GraphQL
syntax errors until it is actually rendered - a mistake in it only surfaces at
runtime, as a failed entity, rather than as a configuration error when the task
is set up. If **Query** contains Jinja syntax and no input is connected at all,
the unrendered `{{ ... }}` text is sent to the GraphQL library as literal
syntax and the task fails outright. If only **Query variables** contains Jinja
syntax while **Query** is static, and no input is connected, the task instead
sends nothing and completes as if zero entities were processed, without
warning that the variables were never rendered.
""",
    parameters=[
        PluginParameter(
            name="graphql_url",
            label="Endpoint",
            description="""The URL of the GraphQL endpoint you want to query.

A collective list of public GraphQL APIs is available
[here](https://github.com/IvanGoncharov/graphql-apis).

Example Endpoint: `https://fruits-api.netlify.app/graphql`
""",
        ),
        PluginParameter(
            name="graphql_query",
            label="Query",
            description="""The query text of the GraphQL Query you want to execute.

GraphQL is a query language for APIs and a runtime for fulfilling those queries with
your existing data. Learn more on GraphQL [here](https://graphql.org/).

May also contain Jinja syntax (e.g. `{{ id }}`), which is rendered against each
input entity before the query is sent.

Example Query: query allFruits {
fruits {
    id
    scientific_name
    tree_name
    fruit_name
    family
    origin
    description
    climatic_zone
    }
}
""",
            param_type=MultilineStringParameterType(),
        ),
        PluginParameter(
            name="graphql_variable_values",
            label="Query variables",
            description="""Pass dynamic variables when making a query or mutation.

May also contain Jinja syntax (e.g. `{"id": {{ id }}}`), which is rendered
against each input entity before the query is sent.

Example Variables: `{"id" : 1}`
""",
            default_value="{}",
            param_type=MultilineStringParameterType(),
        ),
        PluginParameter(
            name="access_token",
            label="Access token",
            description="""The token the endpoint is authenticated with. It is sent as the
`Authorization: Bearer <token>` header.

For GitLab, a personal, project or group access token works, with scope
`read_api` for queries or `api` for mutations.
""",
            param_type=PasswordParameterType(),
            advanced=True,
            default_value="",
        ),
    ],
)
class GraphQLPlugin(WorkflowPlugin):
    """GraphQL Workflow Plugin to query GraphQL APIs"""

    def __init__(
        self,
        graphql_url: str,
        graphql_query: str,
        graphql_variable_values: str = "",
        access_token: Password | str = "",
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
        # An empty payload carries no shape to read a schema off, so build_entities_from_data
        # answers None rather than an empty collection.
        entities = build_entities_from_data(payload)
        if entities is None:
            return Entities(entities=iter([]), schema=self.output_schema or EMPTY_SCHEMA)
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
