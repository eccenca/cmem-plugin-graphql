"""Random values workflow plugin module"""
import uuid
from secrets import token_urlsafe

from cmem_plugin_base.dataintegration.description import Plugin, PluginParameter
from cmem_plugin_base.dataintegration.entity import (
    Entities, Entity, EntitySchema, EntityPath,
)
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.types import StringParameterType
import validators

from cmem_plugin_base.dataintegration.parameter.dataset import DatasetParameterType


@Plugin(
    label="GraphQL (awesome)",
    description="Retrieves the data from GraphQL APIs",
    documentation="""
Executes a GraphQL APIs based on fixed configuration and/or input parameters and returns the result as entity.
""",
    parameters=[
        PluginParameter(
            name="graphql_url",
            label="URL",
            description="The URL to execute this request against. This can be overwritten at execution time via input."
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
class DollyPlugin(WorkflowPlugin):
    """Example Workflow Plugin: Random Values"""

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

    def execute(self, inputs=()) -> None:
        self.log.info("Start querying APIs")

