"""Utils module"""

from collections.abc import Iterator

import jinja2
from cmem_plugin_base.dataintegration.entity import Entities, EntityPath, EntitySchema
from gql import gql
from graphql import GraphQLError
from graphql.language import FieldNode, OperationDefinitionNode


def output_schema_from_query(query: str) -> EntitySchema | None:
    """Derive the output schema of a query, or None when the query does not describe one

    A GraphQL query names the fields it asks for, so the paths of the entities the
    response becomes are known before the endpoint is called. Only the top level of
    the query is described here: a field that selects sub fields becomes a relation
    path, and the schema of the entities behind it is discovered from the response,
    the way `cmem-plugin-llm` handles a nested structured output.

    What the query does not say is how many values a field carries - that is in the
    endpoint's own schema, not in the query - so every path is declared as possibly
    multi valued. Declaring a single value and receiving a list is the direction that
    loses data.

    None means the response shape cannot be read off the query, and the caller should
    fall back to an unknown schema. That is the case for a query that is rendered from
    a Jinja template, one carrying several operations, and one whose top level is a
    fragment rather than plain fields.
    """
    try:
        document = gql(query).document
    except GraphQLError:
        return None
    operations = [d for d in document.definitions if isinstance(d, OperationDefinitionNode)]
    if len(operations) != 1:
        return None
    paths = []
    for selection in operations[0].selection_set.selections:
        if not isinstance(selection, FieldNode):
            return None
        name = selection.alias.value if selection.alias else selection.name.value
        paths.append(
            EntityPath(
                path=name,
                is_relation=selection.selection_set is not None,
                is_single_value=False,
            )
        )
    return EntitySchema(type_uri="", paths=paths)


def get_dict(entities: Entities) -> Iterator[dict[str, str]]:
    """Get dict from entities"""
    paths = entities.schema.paths
    for entity in entities.entities:
        result = {}
        for i, path in enumerate(paths):
            result[path.path] = entity.values[i][0] if entity.values[i] else ""
        yield result


def is_jinja_template(value: str) -> bool:
    """Check value contain jinja variables"""
    environment = jinja2.Environment(autoescape=True)
    template = environment.from_string(value)
    res = template.render()
    return res != value
