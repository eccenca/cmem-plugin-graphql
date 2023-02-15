"""GraphQL workflow plugin module"""

import io
import json
from typing import Sequence, Optional, Dict, Any, Tuple, Iterator

import jinja2
import validators
from cmem_plugin_base.dataintegration.context import ExecutionContext, ExecutionReport
from cmem_plugin_base.dataintegration.description import Plugin, PluginParameter
from cmem_plugin_base.dataintegration.entity import Entities
from cmem_plugin_base.dataintegration.parameter.dataset import DatasetParameterType
from cmem_plugin_base.dataintegration.parameter.multiline import (
    MultilineStringParameterType,
)
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.utils import write_to_dataset
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from graphql import GraphQLSyntaxError, GraphQLError

from cmem_plugin_graphql.workflow.utils import (
    get_dict,
    is_jinja_template,
    get_entities_from_list,
)


@Plugin(
    label="GraphQL query",
    description="Executes a custom GraphQL query to a GraphQL endpoint"
    " and saves result to a JSON dataset.",
    documentation="""This workflow task performs GraphQL operations by sending
     queries, mutations, and variables over operations. Allows for customization
     in the GraphQL query using, Jinja queries and Jinja variables, which can be
     obtained from entities. The result of the query is saved as a JSON document
     in a pre-created JSON dataset.
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

            Example Variables: {"id" : 1}
            """,
            default_value="{}",
            param_type=MultilineStringParameterType(),
        ),
        PluginParameter(
            name="graphql_dataset",
            label="Target JSON Dataset",
            description="The Dataset where this task will save the JSON results.",
            param_type=DatasetParameterType(dataset_type="json"),
            advanced=True,
            default_value="",
        ),
        PluginParameter(
            name="oauth_access_token",
            label="OAuth access token",
            description="Access token that connects to a GraphQL endpoint to"
            " authorize and secure user access to resources and data.",
            advanced=True,
            default_value="",
        ),
    ],
)
class GraphQLPlugin(WorkflowPlugin):
    """GraphQL Workflow Plugin to query GraphQL APIs"""

    # pylint: disable=too-many-arguments
    def __init__(  # nosec
        self,
        graphql_url: str,
        graphql_query: str,
        graphql_variable_values: str = "",
        graphql_dataset: str = "",
        oauth_access_token: str = "",
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
        self.graphql_dataset = graphql_dataset
        self.headers = {}
        if oauth_access_token:
            self.headers["Authorization"] = f"Bearer {oauth_access_token}"

    def set_graphql_variable_values(self, variable_values):
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

    def set_graphql_query(self, query):
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

    def execute(
        self, inputs: Sequence[Entities], context: ExecutionContext
    ) -> Entities:
        self.log.info("Start GraphQL query.")
        dataset_id = (
            f"{context.task.project_id()}:{self.graphql_dataset}"
            if self.graphql_dataset
            else None
        )
        processed_entities: int = 0
        failed_entities: int = 0
        payload = []
        if inputs and self.jinja_query or self.jinja_variable_values:
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
            # Select your transport with a defined url endpoint
            transport = AIOHTTPTransport(url=self.graphql_url, headers=self.headers)
            # Create a GraphQL client using the defined transport
            client = Client(transport=transport, fetch_schema_from_transport=True)
            result = client.execute(
                document=gql(self.graphql_query),
                variable_values=json.loads(self.graphql_variable_values),
            )
            processed_entities += 1
            payload.append(result)

        summary: list[Tuple[str, str]] = []
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
        if dataset_id:
            write_to_dataset(
                dataset_id,
                io.StringIO(json.dumps(payload, indent=2)),
                context=context.user,
            )

        return get_entities_from_list(payload)

    def process_entities(
        self, entities: Entities
    ) -> Iterator[Optional[Dict[str, Any]]]:
        """Process entities"""
        # Select your transport with a defined url endpoint
        transport = AIOHTTPTransport(url=self.graphql_url, headers=self.headers)
        # Create a GraphQL client using the defined transport
        client = Client(transport=transport, fetch_schema_from_transport=True)
        environment = jinja2.Environment(autoescape=True)
        for jinja_variable_values in get_dict(entities):
            result = None
            template = environment.from_string(self.graphql_query)
            query = template.render(jinja_variable_values)

            template = environment.from_string(self.graphql_variable_values)
            variable_values = template.render(jinja_variable_values)
            try:
                result = client.execute(
                    document=gql(query),
                    variable_values=json.loads(variable_values),
                )
            except (
                GraphQLError,
                GraphQLSyntaxError,
                json.decoder.JSONDecodeError,
            ) as ex:
                self.log.error(f"Failed entity: {type(ex)}")

            yield result
