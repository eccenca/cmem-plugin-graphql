"""GraphQL workflow plugin module"""

import io
import json
from typing import Sequence, Dict, Any

import validators
from cmem_plugin_base.dataintegration.context import ExecutionContext
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
from graphql import GraphQLSyntaxError, DocumentNode


@Plugin(
    label="GraphQL query",
    description="Executes a custom GraphQL query to a GraphQL endpoint"
    " and saves result to a JSON dataset.",
    documentation="""This workflow task sends a GraphQL query to a GraphQL endpoint,
retrieves the results and saves it as a JSON document to a JSON Dataset
(which you have to create up-front).""",
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
            description="""GraphQL variables""",
            default_value="",
            param_type=MultilineStringParameterType(),
        ),
        PluginParameter(
            name="graphql_dataset",
            label="Target JSON Dataset",
            description="The Dataset where this task will save the JSON results.",
            param_type=DatasetParameterType(dataset_type="json"),
            advanced=True,
        ),
    ],
)
class GraphQLPlugin(WorkflowPlugin):
    """GraphQL Workflow Plugin to query GraphQL APIs"""

    graphql_variable_values: Dict[str, Any]
    graphql_url: str
    graphql_query: DocumentNode

    def __init__(
        self,
        graphql_url: str,
        graphql_query: str,
        graphql_variable_values: str = None,
        graphql_dataset: str = None,
    ) -> None:

        if not validators.url(graphql_url):
            raise ValueError("Provide a valid GraphQL URL.")
        self.graphql_url = graphql_url

        self.set_graphql_query(graphql_query)
        self.set_graphql_variable_values(graphql_variable_values)

        self.graphql_dataset = graphql_dataset

    def set_graphql_variable_values(self, variable_values):
        """Validate and set graphql_variable_values"""
        try:
            self.graphql_variable_values = (
                json.loads(variable_values) if variable_values is not None else {}
            )
        except json.decoder.JSONDecodeError as ex:
            raise ValueError("Variables String are not a valid json.") from ex

    def set_graphql_query(self, query):
        """Validate and set graphql_query"""
        try:
            self.graphql_query = gql(query)
        except GraphQLSyntaxError as ex:
            raise ValueError("Query string is not Valid.") from ex

    def execute(self, inputs: Sequence[Entities], context: ExecutionContext) -> None:
        self.log.info("Start GraphQL query.")
        dataset_id = f"{context.task.project_id()}:{self.graphql_dataset}"

        # Select your transport with a defined url endpoint
        transport = AIOHTTPTransport(url=self.graphql_url)

        # Create a GraphQL client using the defined transport
        client = Client(transport=transport, fetch_schema_from_transport=True)

        # Execute the query on the transport
        result = client.execute(
            document=self.graphql_query,
            variable_values=self.graphql_variable_values,
        )
        write_to_dataset(
            dataset_id, io.StringIO(json.dumps(result, indent=2)), context=context.user
        )
