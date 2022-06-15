"""GraphQL workflow plugin module"""

import io
import json

import validators
from cmem_plugin_base.dataintegration.description import Plugin, PluginParameter
from cmem_plugin_base.dataintegration.parameter.dataset import DatasetParameterType
from cmem_plugin_base.dataintegration.parameter.multiline import (
    MultilineStringParameterType,
)
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.utils import (
    write_to_dataset
)
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from graphql import GraphQLSyntaxError


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
            name="graphql_dataset",
            label="Target JSON Dataset",
            description="The Dataset where this task will save the JSON results.",
            param_type=DatasetParameterType(dataset_type="json"),
        ),
    ],
)
class GraphQLPlugin(WorkflowPlugin):
    """GraphQL Workflow Plugin to query GraphQL APIs"""

    def __init__(
        self,
        graphql_url: str = None,
        graphql_query: str = None,
        graphql_dataset: str = None,
    ) -> None:

        self.graphql_url = graphql_url
        if not validators.url(graphql_url):
            raise ValueError("Provide a valid GraphQL URL.")

        if not self._is_query_valid(graphql_query):
            raise ValueError("Query string is not Valid")

        self.graphql_query = graphql_query
        self.graphql_dataset = graphql_dataset

    def execute(self, inputs=()):
        self.log.info("Start GraphQL query.")
        # self.log.info(f"Config length: {len(self.config.get())}")

        # Select your transport with a defined url endpoint
        transport = AIOHTTPTransport(url=self.graphql_url)

        # Create a GraphQL client using the defined transport
        client = Client(transport=transport, fetch_schema_from_transport=True)

        # Execute the query on the transport
        result = client.execute(gql(self.graphql_query))
        write_to_dataset(self.graphql_dataset,
                         io.StringIO(json.dumps(result, indent=2)))

    def _is_query_valid(self, query) -> bool:
        try:
            gql(query)
            return True
        except GraphQLSyntaxError:
            return False
