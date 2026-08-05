"""Plugin tests."""

import json
import os
from collections.abc import Generator
from contextlib import suppress
from typing import Any

import pytest
from cmem_client.client import Client
from cmem_client.models.dataset import Dataset
from cmem_client.models.project import Project
from cmem_plugin_base.dataintegration.entity import (
    Entities,
    Entity,
    EntityPath,
    EntitySchema,
)
from cmem_plugin_base.testing import TestExecutionContext
from requests import HTTPError

from cmem_plugin_graphql.workflow.graphql import GraphQLPlugin
from cmem_plugin_graphql.workflow.utils import is_jinja_template

GRAPHQL_URL = "https://cmem-plugin-graphql-test.netlify.app/graphql"

PROJECT_NAME = "graphql_test_project"
DATASET_NAME = "sample_fruit"
RESOURCE_NAME = "sample_fruit.json"

needs_cmem = pytest.mark.skipif(
    os.environ.get("CMEM_BASE_URI", "") == "", reason="Needs CMEM configuration"
)


@pytest.fixture(scope="module")
def project() -> Generator[str]:
    """Provide the DI build project incl. assets."""
    context = TestExecutionContext()
    client = Client.from_context(context=context)

    # Clean up any previous test project
    with suppress(HTTPError):
        client.projects.delete_item(PROJECT_NAME, skip_if_missing=True)

    # Create fresh project and dataset
    client.projects.create_item(Project(name=PROJECT_NAME))
    project_id = next(k for k, v in client.projects.items() if v.name == PROJECT_NAME)
    client.datasets.create_item(
        Dataset(
            id=DATASET_NAME,
            project_id=project_id,
            data={"type": "json", "parameters": {"file": RESOURCE_NAME}},
        )
    )

    yield PROJECT_NAME

    client.projects.delete_item(PROJECT_NAME, skip_if_missing=True)


def _get_client() -> Client:
    """Create a fresh cmem-client from environment."""
    return Client.from_context(context=TestExecutionContext())


def _read_resource(project_name: str, filename: str) -> Any:  # noqa: ANN401
    """Read a JSON resource from a CMEM project."""
    client = _get_client()
    resources = client.files.get_resources(project_name)
    matching = [r for r in resources if r.name == filename]
    if not matching:
        raise HTTPError(f"Resource {filename} not found in project {project_name}")
    resource = matching[0]
    content = client.files.read(f"{project_name}:{resource.full_path}")

    return json.loads(content)


@needs_cmem
def test_execution(project: str) -> None:
    """Test plugin execution"""
    _ = project
    query = "query{fruit(id:1){id,fruit_name}}"
    graphql_response = "{'fruit': {'id': '1', 'fruit_name': 'Manzana'}}"

    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL, graphql_query=query, graphql_dataset=DATASET_NAME
    )
    plugin.execute([], TestExecutionContext(project_id=PROJECT_NAME))
    result = _read_resource(PROJECT_NAME, RESOURCE_NAME)
    assert graphql_response == str(result[0])


@needs_cmem
def test_execution_with_variables(project: str) -> None:
    """Test plugin execution"""
    _ = project
    query = "query manzana($id: ID!){fruit(id: $id){id, fruit_name}}"
    graphql_response = "{'fruit': {'id': '1', 'fruit_name': 'Manzana'}}"
    graphql_variable = '{"id" : 1}'
    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=query,
        graphql_variable_values=graphql_variable,
        graphql_dataset=DATASET_NAME,
    )
    plugin.execute(
        [Entities([Entity("", [[""]])], EntitySchema(",", [EntityPath("")]))],
        TestExecutionContext(project_id=PROJECT_NAME),
    )
    result = _read_resource(PROJECT_NAME, RESOURCE_NAME)
    assert graphql_response == str(result[0])


@needs_cmem
def test_execution_with_jinja_template(project: str) -> None:
    """Test plugin execution"""
    _ = project
    query = "query manzana($id: ID!){fruit(id: $id){id, fruit_name}}"
    graphql_response = "{'fruit': {'id': '1', 'fruit_name': 'Manzana'}}"
    graphql_variable = '{"id" : {{ id }}}'
    plugin = GraphQLPlugin(
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
    result = _read_resource(PROJECT_NAME, RESOURCE_NAME)
    assert graphql_response == str(result[0])


@needs_cmem
def test_mutation(project: str) -> None:
    """Test plugin execution"""
    _ = project
    query = """
    mutation addFruit{
    addFruit(
        id: 1
        scientific_name: "Malus Domestica"
        tree_name: "Apple"
        fruit_name: "Apple"
        family: "Rosaceae"
        origin: "Asia Central"
        description: "The Rosaceae apple, It is a pome-shaped fruit"
        bloom: "Spring"
        maturation_fruit: "Late summer or fall"
        life_cycle: "60-80 years"
        climatic_zone: "cold"
     ) {
        id
        fruit_name
     }
    }
    """
    graphql_response = "{'addFruit': {'id': '1', 'fruit_name': 'Apple'}}"

    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL, graphql_query=query, graphql_dataset=DATASET_NAME
    )
    plugin.execute([], TestExecutionContext(project_id=PROJECT_NAME))
    result = _read_resource(PROJECT_NAME, RESOURCE_NAME)
    assert graphql_response == str(result[0])


@needs_cmem
def test_mutation_with_variables(project: str) -> None:
    """Test plugin execution"""
    _ = project
    query = """
    mutation addFruit($id: ID!, $fruit_name: String!){
    addFruit(
        id: $id
        scientific_name: "Malus Domestica"
        tree_name: "Apple"
        fruit_name: $fruit_name
        family: "Rosaceae"
        origin: "Asia Central"
        description: "The Rosaceae apple, It is a pome-shaped fruit"
        bloom: "Spring"
        maturation_fruit: "Late summer or fall"
        life_cycle: "60-80 years"
        climatic_zone: "cold"
     ) {
        id
        fruit_name
     }
    }
    """
    graphql_response = "{'addFruit': {'id': '1', 'fruit_name': 'Apple'}}"
    graphql_variable = '{"id" : 1, "fruit_name": "Apple"}'

    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=query,
        graphql_variable_values=graphql_variable,
        graphql_dataset=DATASET_NAME,
    )
    plugin.execute([], TestExecutionContext(project_id=PROJECT_NAME))
    result = _read_resource(PROJECT_NAME, RESOURCE_NAME)
    assert graphql_response == str(result[0])


@needs_cmem
def test_mutation_with_jinja_template(project: str) -> None:
    """Test plugin execution"""
    _ = project
    query = """
    mutation addFruit($id: ID!){
    addFruit(
        id: $id
        scientific_name: "Malus Domestica"
        tree_name: "Apple"
        fruit_name: "Apple"
        family: "Rosaceae"
        origin: "Asia Central"
        description: "The Rosaceae apple, It is a pome-shaped fruit"
        bloom: "Spring"
        maturation_fruit: "Late summer or fall"
        life_cycle: "60-80 years"
        climatic_zone: "cold"
     ) {
        id
        fruit_name
     }
    }
    """
    graphql_response = "{'addFruit': {'id': '1', 'fruit_name': 'Apple'}}"
    graphql_variable = '{"id" : {{ id }}}'

    plugin = GraphQLPlugin(
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
    result = _read_resource(PROJECT_NAME, RESOURCE_NAME)
    assert graphql_response == str(result[0])


def test_is_string_jinja_template() -> None:
    """Test plugin execution"""
    query = "query allFruits($id:ID!) { fruit(id:$id) { id scientific_name } }"
    assert not is_jinja_template(query)
    query = "query allFruits($id:ID!) { fruit(id:$id) { id\n scientific_name } }"
    assert not is_jinja_template(query)
    query = "query allFruits($id:ID!) { fruit(id:$id) { id\n scientific_name } }   "
    assert not is_jinja_template(query)
    query = "query allFruits($id:ID!) { fruit(id:$id) { id\n scientific_name } }\n   "
    assert not is_jinja_template(query)


@needs_cmem
def test_validate_invalid_inputs() -> None:
    """Test for invalid parameter inputs."""
    query = "query{fruit(id:1){id,fruit_name}}"

    # Invalid Query
    invalid_query = "query1{fruit(id:1){id,fruit_name}}"
    invalid_url = "fruits_invalid"

    # Invalid URL
    with pytest.raises(ValueError, match=r"Provide a valid GraphQL URL."):
        GraphQLPlugin(graphql_url=invalid_url, graphql_query=query, graphql_dataset=DATASET_NAME)

    # Invalid query
    with pytest.raises(ValueError, match=r"Query string is not Valid"):
        GraphQLPlugin(
            graphql_url=GRAPHQL_URL,
            graphql_query=invalid_query,
            graphql_dataset=DATASET_NAME,
        )

    # Invalid Dateset
    with pytest.raises(HTTPError, match=r"404 Client Error:*"):
        GraphQLPlugin(graphql_url=GRAPHQL_URL, graphql_query=query, graphql_dataset="None").execute(
            [], TestExecutionContext(project_id=PROJECT_NAME)
        )


def test_dummy() -> None:
    """Dummy test to avoid pytest to run amok in case no cmem is available."""
