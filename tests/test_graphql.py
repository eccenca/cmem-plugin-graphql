"""Plugin tests."""
import pytest
from cmem.cmempy.workspace.projects.datasets.dataset import make_new_dataset
from cmem.cmempy.workspace.projects.project import make_new_project, delete_project
from cmem.cmempy.workspace.projects.resources.resource import get_resource_response
from requests import HTTPError

from cmem_plugin_graphql.workflow.graphql import GraphQLPlugin
from .utils import needs_cmem, TestExecutionContext

GRAPHQL_URL = "https://fruits-api.netlify.app/graphql"

PROJECT_NAME = "graphql_test_project"
DATASET_NAME = "sample_fruit"
RESOURCE_NAME = "sample_fruit.json"


@pytest.fixture(scope="module")
def project(request):
    """Provides the DI build project incl. assets."""
    make_new_project(PROJECT_NAME)
    make_new_dataset(
        project_name=PROJECT_NAME,
        dataset_name=DATASET_NAME,
        dataset_type="json",
        parameters={"file": RESOURCE_NAME},
        autoconfigure=False,
    )

    request.addfinalizer(lambda: delete_project(PROJECT_NAME))


@needs_cmem
def test_execution(project):
    """Test plugin execution"""
    query = "query{fruit(id:1){id,fruit_name}}"
    graphql_response = "{'fruit': {'id': '1', 'fruit_name': 'Manzana'}}"

    plugin: GraphQLPlugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL, graphql_query=query, graphql_dataset=DATASET_NAME
    )
    plugin.execute(None, TestExecutionContext(project_id=PROJECT_NAME))
    with get_resource_response(PROJECT_NAME, RESOURCE_NAME) as response:
        print(response.json())
        assert graphql_response == str(response.json())


@needs_cmem
def test_validate_invalid_inputs():
    """Test for invalid parameter inputs."""
    query = "query{fruit(id:1){id,fruit_name}}"

    # Invalid Query
    invalid_query = "query1{fruit(id:1){id,fruit_name}}"
    invalid_url = "fruits_invalid"

    # Invalid URL
    with pytest.raises(ValueError, match="Provide a valid GraphQL URL."):
        GraphQLPlugin(
            graphql_url=invalid_url, graphql_query=query, graphql_dataset=DATASET_NAME
        )

    # Invalid query
    with pytest.raises(ValueError, match="Query string is not Valid"):
        GraphQLPlugin(
            graphql_url=GRAPHQL_URL,
            graphql_query=invalid_query,
            graphql_dataset=DATASET_NAME,
        )

    # Invalid Dateset
    with pytest.raises(HTTPError):
        GraphQLPlugin(
            graphql_url=GRAPHQL_URL, graphql_query=query, graphql_dataset="None"
        ).execute(None, TestExecutionContext(project_id=PROJECT_NAME))


def test_dummy():
    """Dummy test to avoid pytest to run amok in case no cmem is available."""
