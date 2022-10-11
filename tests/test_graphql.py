"""Plugin tests."""
import pytest
from cmem.cmempy.workspace.projects.datasets.dataset import make_new_dataset
from cmem.cmempy.workspace.projects.project import make_new_project, delete_project
from cmem.cmempy.workspace.projects.resources.resource import get_resource_response
from cmem_plugin_base.dataintegration.entity import (
    Entities,
    Entity,
    EntitySchema,
    EntityPath,
)
from requests import HTTPError

from cmem_plugin_graphql.workflow.graphql import GraphQLPlugin
from cmem_plugin_graphql.workflow.utils import is_jinja_template
from .utils import needs_cmem, TestExecutionContext

GRAPHQL_URL = "https://fruits-api.netlify.app/graphql"

PROJECT_NAME = "graphql_test_project"
DATASET_NAME = "sample_fruit"
RESOURCE_NAME = "sample_fruit.json"


@pytest.fixture(scope="module")
def project(request):
    """Provides the DI build project incl. assets."""
    try:
        delete_project(PROJECT_NAME)
    except HTTPError:
        pass
    finally:
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
    plugin.execute([], TestExecutionContext(project_id=PROJECT_NAME))
    with get_resource_response(PROJECT_NAME, RESOURCE_NAME) as response:
        print(response.json())
        assert graphql_response == str(response.json()[0])


@needs_cmem
def test_execution_with_variables(project):
    """Test plugin execution"""
    query = "query manzana($id: ID!){fruit(id: $id){id, fruit_name}}"
    graphql_response = "{'fruit': {'id': '1', 'fruit_name': 'Manzana'}}"
    graphql_variable = '{"id" : 1}'
    plugin: GraphQLPlugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=query,
        graphql_variable_values=graphql_variable,
        graphql_dataset=DATASET_NAME,
    )
    plugin.execute(
        [Entities([Entity("", [[""]])], EntitySchema(",", [EntityPath("")]))],
        TestExecutionContext(project_id=PROJECT_NAME),
    )
    with get_resource_response(PROJECT_NAME, RESOURCE_NAME) as response:
        print(f"Response: {response.json()}")
        assert graphql_response == str(response.json()[0])


def test_execution_with_jinja_template(project):
    """Test plugin execution"""
    query = "query manzana($id: ID!){fruit(id: $id){id, fruit_name}}"
    graphql_response = "{'fruit': {'id': '1', 'fruit_name': 'Manzana'}}"
    graphql_variable = '{"id" : {{ id }}}'
    plugin: GraphQLPlugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=query,
        graphql_variable_values=graphql_variable,
        graphql_dataset=DATASET_NAME,
    )
    # generate entities
    path = EntityPath(path="id")
    schema = EntitySchema(type_uri="", paths=[path])
    entity = Entity(uri="", values=[[1]])
    plugin.execute(
        [Entities(entities=[entity], schema=schema)],
        TestExecutionContext(project_id=PROJECT_NAME),
    )
    with get_resource_response(PROJECT_NAME, RESOURCE_NAME) as response:
        print(f"Response: {response.json()}")
        assert graphql_response == str(response.json()[0])


def test_is_string_jinja_template():
    query = "query allFruits($id:ID!) { fruit(id:$id) { id scientific_name } }"
    assert not is_jinja_template(query)
    query = "query allFruits($id:ID!) { fruit(id:$id) { id\n scientific_name } }"
    assert not is_jinja_template(query)
    query = "query allFruits($id:ID!) { fruit(id:$id) { id\n scientific_name } }   "
    assert not is_jinja_template(query)
    query = "query allFruits($id:ID!) { fruit(id:$id) { id\n scientific_name } }\n   "
    assert not is_jinja_template(query)


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
    with pytest.raises(HTTPError, match="404 Client Error:*"):
        GraphQLPlugin(
            graphql_url=GRAPHQL_URL, graphql_query=query, graphql_dataset="None"
        ).execute([], TestExecutionContext(project_id=PROJECT_NAME))


def test_dummy():
    """Dummy test to avoid pytest to run amok in case no cmem is available."""
