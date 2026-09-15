"""Plugin tests."""

import os

import pytest
from cmem_plugin_base.dataintegration.context import ExecutionContext, ReportContext
from cmem_plugin_base.dataintegration.entity import (
    Entities,
    Entity,
    EntityPath,
    EntitySchema,
)
from cmem_plugin_base.dataintegration.parameter.password import Password
from cmem_plugin_base.testing import TestSystemContext

from cmem_plugin_graphql.workflow.graphql import GraphQLPlugin
from cmem_plugin_graphql.workflow.utils import is_jinja_template

GRAPHQL_URL = "https://cmem-plugin-graphql-test.netlify.app/graphql"

# ``TESTING_GITLAB_URL`` names a GitLab instance; its GraphQL endpoint is always
# ``/api/graphql`` on that instance. A configuration that spells the full endpoint out
# is accepted as well, since both readings of the variable name are reasonable.
GITLAB_INSTANCE = os.environ.get("TESTING_GITLAB_URL", "https://gitlab.com").rstrip("/")
GITLAB_URL = (
    GITLAB_INSTANCE
    if GITLAB_INSTANCE.endswith("/api/graphql")
    else f"{GITLAB_INSTANCE}/api/graphql"
)
GITLAB_TOKEN = os.environ.get("TESTING_GITLAB_TOKEN", "")

needs_gitlab = pytest.mark.skipif(
    GITLAB_TOKEN == "", reason="Needs TESTING_GITLAB_TOKEN configuration"
)


# Passed through a variable rather than inline: ruff reads a string literal handed to an
# argument named like a secret as a hardcoded credential (S106). The variable itself must
# not be named like one either, or S105 says the same thing about the assignment.
CONFIGURED_VALUE = "value-from-the-access-token-parameter"


def password(value: str) -> Password:
    """Build a Password as DataIntegration would hand one to the plugin.

    ``TestSystemContext`` encrypts and decrypts by returning the value unchanged, and
    constructs nothing user-bound, so this needs no Corporate Memory deployment.
    """
    return Password(TestSystemContext().encrypt(value), TestSystemContext())


FRUIT_QUERY = "query{fruit(id:1){id,fruit_name}}"
FRUIT_QUERY_WITH_VARIABLE = "query manzana($id: ID!){fruit(id: $id){id, fruit_name}}"
MANZANA = [["1"], ["Manzana"]]

ADD_FRUIT_MUTATION = """
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

ADD_FRUIT_MUTATION_WITH_VARIABLES = """
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

APPLE = [["1"], ["Apple"]]


class StubExecutionContext(ExecutionContext):
    """An execution context which needs no Corporate Memory deployment.

    ``GraphQLPlugin.execute()`` touches nothing but ``context.report``, so every code
    path can be covered without credentials. ``TestExecutionContext`` is unusable here
    because it builds a ``TestUserContext``, which fetches an OAuth token while it is
    constructed.
    """

    def __init__(self) -> None:
        self.report = ReportContext()


def id_entities(value: int) -> Entities:
    """Build a single input entity carrying `value` under the path `id`."""
    return Entities(
        entities=iter([Entity(uri="", values=[[str(value)]])]),
        schema=EntitySchema(type_uri="", paths=[EntityPath(path="id")]),
    )


def assert_is_manzana(entities: Entities) -> None:
    """Assert that the entities are the fruit with id 1, nested under a `fruit` path."""
    assert [path.path for path in entities.schema.paths] == ["fruit"]
    fruit = entities.sub_entities[0]
    assert [path.path for path in fruit.schema.paths] == ["id", "fruit_name"]
    assert [entity.values for entity in fruit.entities] == [MANZANA]


def assert_is_added_apple(entities: Entities) -> None:
    """Assert that the entities are the apple the mutation added."""
    assert [path.path for path in entities.schema.paths] == ["addFruit"]
    fruit = entities.sub_entities[0]
    assert [path.path for path in fruit.schema.paths] == ["id", "fruit_name"]
    assert [entity.values for entity in fruit.entities] == [APPLE]


def test_execution() -> None:
    """Test a plain query against the endpoint"""
    plugin = GraphQLPlugin(graphql_url=GRAPHQL_URL, graphql_query=FRUIT_QUERY)
    assert_is_manzana(plugin.execute([], StubExecutionContext()))


def test_execution_with_variables() -> None:
    """Test a query with static variables"""
    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : 1}',
    )
    assert_is_manzana(plugin.execute([], StubExecutionContext()))


def test_execution_with_jinja_template() -> None:
    """Test that a Jinja template in the variables queries once per input entity"""
    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : {{ id }}}',
    )
    assert_is_manzana(plugin.execute([id_entities(1)], StubExecutionContext()))


def test_execution_preserves_unicode_characters() -> None:
    """Test that non-ASCII characters from the GraphQL response reach the entities intact"""
    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query="query{fruit(id:4){id,scientific_name,fruit_name,family}}",
    )
    entities = plugin.execute([], StubExecutionContext())
    fruit = entities.sub_entities[0]
    values = dict(
        zip(
            [path.path for path in fruit.schema.paths],
            next(iter(fruit.entities)).values,
            strict=True,
        )
    )
    assert values["fruit_name"] == ["Limón"]
    assert values["family"] == ["Rutáceae"]


def test_mutation() -> None:
    """Test a mutation without variables"""
    plugin = GraphQLPlugin(graphql_url=GRAPHQL_URL, graphql_query=ADD_FRUIT_MUTATION)
    assert_is_added_apple(plugin.execute([], StubExecutionContext()))


def test_mutation_with_variables() -> None:
    """Test a mutation with static variables"""
    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=ADD_FRUIT_MUTATION_WITH_VARIABLES,
        graphql_variable_values='{"id" : 1, "fruit_name": "Apple"}',
    )
    assert_is_added_apple(plugin.execute([], StubExecutionContext()))


def test_mutation_with_jinja_template() -> None:
    """Test a mutation whose variables are rendered from an input entity"""
    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=ADD_FRUIT_MUTATION_WITH_VARIABLES,
        graphql_variable_values='{"id" : {{ id }}, "fruit_name": "Apple"}',
    )
    assert_is_added_apple(plugin.execute([id_entities(1)], StubExecutionContext()))


def test_process_entities_renders_jinja_variables() -> None:
    """Test that Jinja variables are rendered from the input entities"""
    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL,
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : {{ id }}}',
    )
    assert list(plugin.process_entities(id_entities(1))) == [
        {"fruit": {"id": "1", "fruit_name": "Manzana"}}
    ]


def test_process_entities_yields_none_on_transport_error() -> None:
    """Test that an unreachable endpoint fails the entity instead of the whole task"""
    plugin = GraphQLPlugin(
        graphql_url="https://127.0.0.1:1/graphql",
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : {{ id }}}',
    )
    assert list(plugin.process_entities(id_entities(1))) == [None]


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


def test_validate_invalid_inputs() -> None:
    """Test for invalid parameter inputs."""
    query = "query{fruit(id:1){id,fruit_name}}"
    invalid_query = "query1{fruit(id:1){id,fruit_name}}"
    invalid_url = "fruits_invalid"

    # Invalid URL
    with pytest.raises(ValueError, match=r"Provide a valid GraphQL URL."):
        GraphQLPlugin(graphql_url=invalid_url, graphql_query=query)

    # Invalid query
    with pytest.raises(ValueError, match=r"Query string is not Valid"):
        GraphQLPlugin(graphql_url=GRAPHQL_URL, graphql_query=invalid_query)


def test_access_token_is_sent_as_bearer_header() -> None:
    """Test that the access token becomes an Authorization header"""
    plugin = GraphQLPlugin(
        graphql_url=GRAPHQL_URL, graphql_query=FRUIT_QUERY, access_token=password(CONFIGURED_VALUE)
    )
    assert plugin.headers == {"Authorization": f"Bearer {CONFIGURED_VALUE}"}


def test_no_token_sends_no_authorization_header() -> None:
    """Test that no header is sent when no token is configured"""
    plugin = GraphQLPlugin(graphql_url=GRAPHQL_URL, graphql_query=FRUIT_QUERY)
    assert plugin.headers == {}


@needs_gitlab
def test_gitlab_query_with_access_token() -> None:
    """Test a query against a GitLab endpoint authenticated with an access token.

    ``currentUser`` is valid on every GitLab instance and answers with the user the
    token belongs to, so a non-empty username proves the header was honoured rather
    than only that the endpoint could be reached.
    """
    plugin = GraphQLPlugin(
        graphql_url=GITLAB_URL,
        graphql_query="query { currentUser { username } }",
        access_token=password(GITLAB_TOKEN),
    )
    entities = plugin.execute([], StubExecutionContext())
    assert [path.path for path in entities.schema.paths] == ["currentUser"]
    current_user = entities.sub_entities[0]
    assert [path.path for path in current_user.schema.paths] == ["username"]
    usernames = [entity.values[0][0] for entity in current_user.entities]
    assert len(usernames) == 1
    assert usernames[0]
