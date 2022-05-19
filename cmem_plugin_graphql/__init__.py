"""GraphQL workflow plugin module"""
import uuid
from typing import List

import validators
from cmem.cmempy.workspace.projects.resources.resource import create_resource
from cmem_plugin_base.dataintegration.description import Plugin, PluginParameter
from cmem_plugin_base.dataintegration.entity import Entity, Entities, EntityPath, EntitySchema
from cmem_plugin_base.dataintegration.parameter.dataset import DatasetParameterType
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.utils import setup_cmempy_super_user_access
import io
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
import json
from cmem.cmempy.workspace.tasks import get_task


@Plugin(
    label="GraphQL ",
    description="Retrieves the data from GraphQL APIs",
    documentation="""
Executes a GraphQL APIs based on fixed configuration and/or
input parameters and returns the result as entity.
""",
    parameters=[
        PluginParameter(
            name="graphql_url",
            label="URL",
            description="""The URL to execute this request against.
            This can be overwritten at execution time via input."""
        ),
        PluginParameter(
            name="graphql_query",
            label="Query",
            description="GraphQL Query",

        ),
        PluginParameter(
            name="graphql_dataset",
            label="Dataset",
            description="To which Dataset to write the response",
            param_type=DatasetParameterType(dataset_type="json")
        )
    ]
)
class GraphQLPlugin(WorkflowPlugin):
    """GraphQL Workflow Plugin to query GraphQL APIs"""

    def __init__(
            self,
            graphql_url: str = None,
            graphql_query: str = None,
            graphql_dataset: str = None
    ) -> None:
        self.graphql_url = graphql_url
        if not validators.url(graphql_url):
            raise ValueError(
                "Provide a valid GraphQL URL."
            )
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

        self._write_response_to_resource(result)

    def _write_response_to_resource(self, response) -> None:
        setup_cmempy_super_user_access()
        project_resource = self.graphql_dataset.split(":")
        file_path = f'dummy.txt'
        file = open(file_path, "w+")
        file.write(json.dumps(response))
        file.close()
        with open(file_path, 'rb') as response_file:
            create_resource(
                project_name=project_resource[0],
                resource_name=project_resource[1],
                file_resource=response_file,
                replace=True,
            )
