"""Plugin tests."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cmem_plugin_base.dataintegration.context import ExecutionContext, ReportContext
from cmem_plugin_base.dataintegration.discovery import discover_plugins
from cmem_plugin_base.dataintegration.entity import (
    Entities,
    Entity,
    EntityPath,
    EntitySchema,
)
from cmem_plugin_base.dataintegration.parameter.password import Password
from cmem_plugin_base.dataintegration.ports import FixedSchemaPort, UnknownSchemaPort
from cmem_plugin_base.dataintegration.typed_entities.file import FileEntitySchema
from cmem_plugin_base.dataintegration.utils.entity_builder import build_entities_from_data
from cmem_plugin_base.testing import TestSystemContext

from cmem_plugin_graphql.workflow.graphql import OUTPUT, RESULT_FILE_NAME, GraphQLPlugin
from cmem_plugin_graphql.workflow.utils import (
    entities_from_payload,
    input_schema_from_templates,
    is_jinja_template,
    output_schema_from_query,
    render_template,
    without_dangling_relations,
)

# The tests that really call an endpoint are opt-in, the way the plugin-testing skill
# guards anything reaching an external API. Three of them are mutations, and they write
# to a public endpoint nobody here owns, so they must not run on every push of every
# branch. Set TESTING_GRAPHQL_ENDPOINT to the endpoint to run them.
GRAPHQL_URL = os.environ.get(
    "TESTING_GRAPHQL_ENDPOINT", "https://cmem-plugin-graphql-test.netlify.app/graphql"
)

needs_endpoint = pytest.mark.skipif(
    os.environ.get("TESTING_GRAPHQL_ENDPOINT", "") == "",
    reason="Needs TESTING_GRAPHQL_ENDPOINT configuration",
)

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


def build_plugin(
    graphql_query: str,
    graphql_url: str = GRAPHQL_URL,
    access_token: Password | str = "",
    output_mode: str = OUTPUT.entities,
    graphql_variable_values: str = "",
) -> GraphQLPlugin:
    """Build the plugin against the test endpoint, with the boring arguments filled in.

    ``access_token`` and ``output_mode`` carry no Python default in the plugin itself -
    they precede a parameter that has none - so a test indifferent to either would
    otherwise have to repeat both at every call.
    """
    return GraphQLPlugin(
        graphql_url=graphql_url,
        access_token=access_token,
        output_mode=output_mode,
        graphql_query=graphql_query,
        graphql_variable_values=graphql_variable_values,
    )


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


@needs_endpoint
def test_execution() -> None:
    """Test a plain query against the endpoint"""
    plugin = build_plugin(graphql_query=FRUIT_QUERY)
    assert_is_manzana(plugin.execute([], StubExecutionContext()))


@needs_endpoint
def test_execution_with_variables() -> None:
    """Test a query with static variables"""
    plugin = build_plugin(
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : 1}',
    )
    assert_is_manzana(plugin.execute([], StubExecutionContext()))


@needs_endpoint
def test_execution_with_jinja_template() -> None:
    """Test that a Jinja template in the variables queries once per input entity"""
    plugin = build_plugin(
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : {{ id }}}',
    )
    assert_is_manzana(plugin.execute([id_entities(1)], StubExecutionContext()))


@needs_endpoint
def test_execution_preserves_unicode_characters() -> None:
    """Test that non-ASCII characters from the GraphQL response reach the entities intact"""
    plugin = build_plugin(
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


@needs_endpoint
def test_mutation() -> None:
    """Test a mutation without variables"""
    plugin = build_plugin(graphql_query=ADD_FRUIT_MUTATION)
    assert_is_added_apple(plugin.execute([], StubExecutionContext()))


@needs_endpoint
def test_mutation_with_variables() -> None:
    """Test a mutation with static variables"""
    plugin = build_plugin(
        graphql_query=ADD_FRUIT_MUTATION_WITH_VARIABLES,
        graphql_variable_values='{"id" : 1, "fruit_name": "Apple"}',
    )
    assert_is_added_apple(plugin.execute([], StubExecutionContext()))


@needs_endpoint
def test_mutation_with_jinja_template() -> None:
    """Test a mutation whose variables are rendered from an input entity"""
    plugin = build_plugin(
        graphql_query=ADD_FRUIT_MUTATION_WITH_VARIABLES,
        graphql_variable_values='{"id" : {{ id }}, "fruit_name": "Apple"}',
    )
    assert_is_added_apple(plugin.execute([id_entities(1)], StubExecutionContext()))


@needs_endpoint
def test_process_entities_renders_jinja_variables() -> None:
    """Test that Jinja variables are rendered from the input entities"""
    plugin = build_plugin(
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : {{ id }}}',
    )
    assert list(plugin.process_entities(id_entities(1))) == [
        {"fruit": {"id": "1", "fruit_name": "Manzana"}}
    ]


def test_process_entities_yields_none_on_transport_error() -> None:
    """Test that an unreachable endpoint fails the entity instead of the whole task"""
    plugin = build_plugin(
        graphql_url="https://127.0.0.1:1/graphql",
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : {{ id }}}',
    )
    assert list(plugin.process_entities(id_entities(1))) == [None]


def test_execution_without_a_query_sent_returns_no_entities() -> None:
    """Test that a run which sent nothing still answers on the output port.

    A Jinja template in the variables with no input connected queries nothing at all,
    so there is no response to read a schema off.
    """
    plugin = build_plugin(
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : {{ id }}}',
    )
    entities = plugin.execute([], StubExecutionContext())
    assert list(entities.entities) == []
    assert [path.path for path in entities.schema.paths] == ["fruit"]


def test_output_schema_names_the_fields_the_query_asks_for() -> None:
    """Test that the top level of the query becomes the schema paths"""
    schema = output_schema_from_query("query { fruit(id:1) { id } tree(id:2) { name } version }")
    assert schema is not None
    assert [(p.path, p.is_relation) for p in schema.paths] == [
        ("fruit", True),
        ("tree", True),
        ("version", False),
    ]


def test_output_schema_uses_the_alias_a_field_is_given() -> None:
    """Test that an aliased field is named by its alias, which is the key in the response"""
    schema = output_schema_from_query("query { a: fruit(id:1) { id } b: fruit(id:2) { id } }")
    assert schema is not None
    assert [p.path for p in schema.paths] == ["a", "b"]


def test_output_schema_declares_every_path_as_multi_valued() -> None:
    """Test that cardinality, which the query does not state, is never declared as single"""
    schema = output_schema_from_query(FRUIT_QUERY)
    assert schema is not None
    assert all(not path.is_single_value for path in schema.paths)


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("query manzana{fruit(id: {{ id }}){id}}", id="jinja placeholder"),
        pytest.param(
            "query A { fruit(id:1){id} } query B { fruit(id:2){id} }", id="two operations"
        ),
        pytest.param("query { ...f } fragment f on Query { fruit(id:1){id} }", id="root fragment"),
    ],
)
def test_output_schema_is_undecidable_for(query: str) -> None:
    """Test that a query which does not describe its response answers None"""
    assert output_schema_from_query(query) is None


def test_output_port_is_fixed_when_the_query_describes_its_response() -> None:
    """Test that a plain query offers its schema to the next task"""
    plugin = build_plugin(graphql_query=FRUIT_QUERY)
    assert isinstance(plugin.output_port, FixedSchemaPort)
    assert [path.path for path in plugin.output_port.schema.paths] == ["fruit"]


def test_output_port_is_unknown_when_the_query_does_not() -> None:
    """Test that a query only settled at runtime offers no schema"""
    plugin = build_plugin(
        graphql_query="query manzana{fruit(id: {{ id }}){id}}",
    )
    assert isinstance(plugin.output_port, UnknownSchemaPort)


@needs_endpoint
def test_declared_schema_is_the_schema_of_the_entities() -> None:
    """Test that what the port promised is exactly what execute() returns.

    A consumer holds the declaration against the entities: a JSON dataset sink
    configured from a path declared multi valued and then handed a single object
    fails with *Current context not Array but Object*. ``fruit(id:1)`` answers with
    one object, which is the case that mismatched while the entities were built from
    the response rather than from the declaration.
    """
    plugin = build_plugin(graphql_query=FRUIT_QUERY)
    entities = plugin.execute([], StubExecutionContext())
    assert entities.schema == plugin.output_port.schema


@needs_endpoint
def test_a_relation_path_carries_sub_entity_uris() -> None:
    """Test that a path declared as a relation answers with a list of URIs to resolve"""
    plugin = build_plugin(graphql_query=FRUIT_QUERY)
    entities = plugin.execute([], StubExecutionContext())
    uris = [value for entity in entities.entities for value in entity.values]
    assert uris == [[entity.uri for entity in entities.sub_entities[0].entities]]


def test_a_null_object_leaves_no_placeholder_in_a_relation() -> None:
    """Test that a field null for one item and an object for another stays writable.

    ``build_entities_from_data`` calls such a field a relation, because one item does
    carry an object, and then writes ``[""]`` for the item where it was null. An empty
    string is not a sub entity URI: a JSON dataset sink handed one aborts the whole
    write with *Current context not Array but Object*, which is how a GitLab query
    asking for a ``createdByUser`` that nobody set took a workflow down.
    """
    schema = output_schema_from_query("query { project { states { createdByUser { name } } } }")
    assert schema is not None
    entities = entities_from_payload(
        [{"project": {"states": [{"createdByUser": None}, {"createdByUser": {"name": "a"}}]}}],
        schema,
    )
    for collection in entities.sub_entities or []:
        relations = [index for index, p in enumerate(collection.schema.paths) if p.is_relation]
        for entity in collection.entities:
            for index in relations:
                assert "" not in entity.values[index]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param([{"fruit": {"id": "1"}}], 1, id="one object"),
        pytest.param([{"fruit": [{"id": "1"}, {"id": "2"}]}], 2, id="a list"),
        pytest.param([{"fruit": None}], 0, id="null"),
        pytest.param([{}], 0, id="field absent from the response"),
    ],
)
def test_entities_conform_to_the_declared_schema(payload: list[dict], expected: int) -> None:
    """Test that the declaration holds whatever the endpoint answers with.

    The entity builder in cmem-plugin-base reads its schema off the data, so these
    four responses describe the same query four different ways - single valued for
    the object, multi valued for the list, and not even a relation for the other two.
    A declared schema has to survive all of them.
    """
    schema = output_schema_from_query(FRUIT_QUERY)
    assert schema is not None
    entities = entities_from_payload(payload, schema)
    assert entities.schema == schema
    root = next(iter(entities.entities))
    assert len(root.values[0]) == expected


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
        build_plugin(graphql_url=invalid_url, graphql_query=query)

    # Invalid query
    with pytest.raises(ValueError, match=r"Query string is not Valid"):
        build_plugin(graphql_query=invalid_query)


def test_access_token_is_sent_as_bearer_header() -> None:
    """Test that the access token becomes an Authorization header"""
    plugin = build_plugin(graphql_query=FRUIT_QUERY, access_token=password(CONFIGURED_VALUE))
    assert plugin.headers == {"Authorization": f"Bearer {CONFIGURED_VALUE}"}


def test_no_token_sends_no_authorization_header() -> None:
    """Test that no header is sent when no token is configured"""
    plugin = build_plugin(graphql_query=FRUIT_QUERY)
    assert plugin.headers == {}


@needs_gitlab
def test_gitlab_query_with_access_token() -> None:
    """Test a query against a GitLab endpoint authenticated with an access token.

    ``currentUser`` is valid on every GitLab instance and answers with the user the
    token belongs to, so a non-empty username proves the header was honoured rather
    than only that the endpoint could be reached.
    """
    plugin = build_plugin(
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


@needs_endpoint
def test_file_mode_hands_on_one_json_file() -> None:
    """Test that the file shape writes the responses and hands the file on"""
    plugin = build_plugin(graphql_query=FRUIT_QUERY, output_mode=OUTPUT.file)
    entities = plugin.execute([], StubExecutionContext())
    assert entities.schema.type_uri == FileEntitySchema().type_uri
    files = [FileEntitySchema().from_entity(entity) for entity in entities.entities]
    assert len(files) == 1
    assert Path(files[0].path).name == RESULT_FILE_NAME
    assert files[0].mime == "application/json"
    assert json.loads(Path(files[0].path).read_text(encoding="utf-8")) == [
        {"fruit": {"id": "1", "fruit_name": "Manzana"}}
    ]


@needs_endpoint
def test_file_mode_writes_non_ascii_as_text() -> None:
    """Test that the written file keeps non-ASCII characters instead of escaping them"""
    plugin = build_plugin(
        graphql_query="query{fruit(id:4){fruit_name,family}}", output_mode=OUTPUT.file
    )
    entities = plugin.execute([], StubExecutionContext())
    file = FileEntitySchema().from_entity(next(iter(entities.entities)))
    content = Path(file.path).read_text(encoding="utf-8")
    assert "Limón" in content
    assert "\\u00f3" not in content


def test_file_mode_offers_the_file_schema_whatever_the_query() -> None:
    """Test that the port describes a file, including for a query with no derivable schema"""
    for query in (FRUIT_QUERY, "query manzana{fruit(id: {{ id }}){id}}"):
        plugin = build_plugin(graphql_query=query, output_mode=OUTPUT.file)
        assert isinstance(plugin.output_port, FixedSchemaPort)
        assert plugin.output_port.schema.type_uri == FileEntitySchema().type_uri


def test_an_unknown_output_mode_is_rejected() -> None:
    """Test that a mode outside the choices fails while the task is built"""
    with pytest.raises(ValueError, match=r"Provide a valid output mode"):
        build_plugin(graphql_query=FRUIT_QUERY, output_mode="dataset")


def test_the_parameters_are_offered_in_the_intended_order() -> None:
    """Test the parameter surface DataIntegration renders.

    The order follows the constructor signature rather than the decorator, and both
    optional parameters precede one that has no default, so neither can carry a Python
    default - it is ``default_value`` here that keeps them out of the required set.
    """
    plugin = next(
        _ for _ in discover_plugins("cmem_plugin_graphql").plugins if _.label == "GraphQL query"
    )
    assert [(_.name, _.advanced, _.default_value) for _ in plugin.parameters] == [
        ("graphql_url", False, None),
        ("access_token", False, ""),
        ("output_mode", False, OUTPUT.entities),
        ("graphql_query", False, None),
        ("graphql_variable_values", False, "{}"),
    ]


def test_a_query_without_a_derivable_schema_is_cleaned_too() -> None:
    """Test that the null-object placeholder is removed on the fallback path as well.

    A Jinja query derives no schema, so it leaves through ``build_entities_from_data``
    rather than ``entities_from_payload``. That path used to hand the placeholder on
    untouched, which is the one path the templated GitLab case always takes.
    """
    payload = [{"project": {"createdByUser": None}}, {"project": {"createdByUser": {"name": "a"}}}]
    entities = build_entities_from_data(payload)
    assert entities is not None
    cleaned = without_dangling_relations(entities)
    for collection in [cleaned, *(cleaned.sub_entities or [])]:
        relations = [index for index, p in enumerate(collection.schema.paths) if p.is_relation]
        for entity in collection.entities:
            for index in relations:
                assert "" not in entity.values[index]


def test_rendering_does_not_html_escape_the_values() -> None:
    """Test that a value keeps its own characters on the way into a query.

    Autoescaping turns `O'Brien & Co` into `O&#39;Brien &amp; Co`, so the endpoint is
    asked about, or told to store, a string the user never typed. GraphQL and JSON are
    not HTML, which is why the rule asking for autoescaping is wrong here.
    """
    rendered = render_template('{"name": "{{ name }}"}', {"name": "O'Brien & Co"})
    assert rendered == '{"name": "O\'Brien & Co"}'
    assert json.loads(rendered)["name"] == "O'Brien & Co"


def test_a_canceled_workflow_stops_sending_queries() -> None:
    """Test that cancelling a run stops the loop instead of working through every entity"""

    class CancelingContext(StubExecutionContext):
        """A context reporting the state a user leaves behind by pressing cancel."""

        def __init__(self) -> None:
            super().__init__()
            self.workflow = SimpleNamespace(status=lambda: "Canceling")

    plugin = build_plugin(
        graphql_query=FRUIT_QUERY_WITH_VARIABLE,
        graphql_variable_values='{"id" : {{ id }}}',
    )
    sent = list(plugin.process_entities(id_entities(1), context=CancelingContext()))
    assert sent == []


def test_a_field_selected_twice_is_one_path() -> None:
    """Test that two selections of the same field describe one key, as the response does"""
    schema = output_schema_from_query("query { fruit { id } fruit { fruit_name } }")
    assert schema is not None
    assert [(p.path, p.is_relation) for p in schema.paths] == [("fruit", True)]
    entities = entities_from_payload([{"fruit": {"id": "1", "fruit_name": "Manzana"}}], schema)
    assert len(list(entities.entities)) == 1
    assert len(entities.sub_entities or []) == 1


def test_one_relation_path_is_described_once_across_responses() -> None:
    """Test that a path answered differently per response still has one description.

    Built per response, a path holding an object in one and null in another produced
    two collections that contradicted each other about the same path.
    """
    schema = output_schema_from_query("query { project { createdByUser { name } } }")
    assert schema is not None
    entities = entities_from_payload(
        [{"project": {"createdByUser": None}}, {"project": {"createdByUser": {"name": "a"}}}],
        schema,
    )
    described = [
        [(p.path, p.is_relation) for p in collection.schema.paths]
        for collection in entities.sub_entities or []
    ]
    assert described.count([("createdByUser", True)]) == 1


def test_root_entities_do_not_reuse_identifiers() -> None:
    """Test that two runs hand out different identifiers, as two tasks in one workflow do"""
    schema = output_schema_from_query(FRUIT_QUERY)
    assert schema is not None
    payload = [{"fruit": {"id": "1"}}]
    first = [_.uri for _ in entities_from_payload(payload, schema).entities]
    second = [_.uri for _ in entities_from_payload(payload, schema).entities]
    assert first != second


def test_values_that_are_not_text_are_written_as_json() -> None:
    """Test that a value keeps its JSON form rather than arriving as Python's own"""
    schema = output_schema_from_query("query { version flags meta }")
    assert schema is not None
    entities = entities_from_payload(
        [{"version": 2, "flags": [True, None], "meta": {"major": 1}}], schema
    )
    root = next(iter(entities.entities))
    assert root.values == [["2"], ["true", "null"], ['{"major": 1}']]


def test_a_field_answered_with_different_kinds_of_value_says_so() -> None:
    """Test that mixed value kinds fail with a message naming the field, not AttributeError"""
    schema = output_schema_from_query("query { fruits { id meta { k } } }")
    assert schema is not None
    with pytest.raises(ValueError, match=r"different kinds of value"):
        entities_from_payload(
            [{"fruits": [{"id": "1", "meta": "x"}, {"id": "2", "meta": {"k": 1}}]}], schema
        )


def test_a_shorthand_query_is_reported_as_a_read() -> None:
    """Test that the report calls an anonymous query a read rather than a write"""
    plugin = build_plugin(graphql_query="{ fruit(id:1) { id } }")
    assert plugin._operation() == "read"  # noqa: SLF001


def test_a_mutation_is_reported_as_a_write() -> None:
    """Test that a mutation is still reported as a write"""
    plugin = build_plugin(graphql_query=ADD_FRUIT_MUTATION)
    assert plugin._operation() == "write"  # noqa: SLF001


def test_a_template_that_cannot_parse_is_left_to_its_rendering() -> None:
    """Test that a placeholder where GraphQL expects a value is still accepted"""
    plugin = build_plugin(graphql_query="query manzana{fruit(id: {{ id }}){id}}")
    assert plugin.jinja_query


def test_the_plugin_identifier_never_moves() -> None:
    """Test the identifier deployed tasks reference.

    It was generated from the module path and the class name until 7.0.0, so moving the
    module or renaming the class silently changed the identity of every task built on
    it. It is set explicitly now, and changing this value again orphans every task in
    the field - which is why it moved in a release that already required them to be
    reconfigured, and must not move in one that does not.
    """
    plugin = next(iter(discover_plugins("cmem_plugin_graphql").plugins))
    assert plugin.plugin_id == "cmem_plugin_graphql-Query"


def test_the_input_schema_names_the_jinja_variables() -> None:
    """Test that the paths the templates ask for are the paths the task requests"""
    schema = input_schema_from_templates(
        "query manzana($id: ID!){fruit(id: $id){ {{ field }} }}", '{"id": {{ id }}}'
    )
    assert schema is not None
    assert [(p.path, p.is_single_value) for p in schema.paths] == [("field", True), ("id", True)]


def test_a_task_without_jinja_declares_no_input() -> None:
    """Test that a task ignoring its input offers no handle to connect one to"""
    plugin = build_plugin(graphql_query=FRUIT_QUERY)
    assert plugin.input_ports.ports == []


def test_a_task_with_jinja_requests_the_paths_it_renders() -> None:
    """Test that the declared input port names the paths, rather than leaving them unknown.

    A port that names no paths is handed nothing: DataIntegration reads only what the
    consuming task asks for.
    """
    plugin = build_plugin(
        graphql_query=FRUIT_QUERY_WITH_VARIABLE, graphql_variable_values='{"id" : {{ id }}}'
    )
    ports = plugin.input_ports.ports
    assert len(ports) == 1
    assert [p.path for p in ports[0].schema.paths] == ["id"]
