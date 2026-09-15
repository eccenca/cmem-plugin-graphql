"""Utils module"""

from collections.abc import Iterator
from typing import Any

import jinja2
from cmem_plugin_base.dataintegration.entity import Entities, Entity, EntityPath, EntitySchema
from cmem_plugin_base.dataintegration.utils.entity_builder import build_entities_from_data
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
    multi valued, which is the only declaration that can carry both a single object
    and a list. `entities_from_payload` then builds the entities to match, because a
    consumer holds the declaration against the entities it receives: a dataset sink
    configured for an array and handed an object fails with *Current context not
    Array but Object* rather than adapting to it.

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


def entities_from_payload(payload: list[dict[str, Any]], schema: EntitySchema) -> Entities:
    """Build entities that conform to `schema`, one root entity per response

    `build_entities_from_data` reads its schema off the data, so the same query
    produces a different one per response: a field answering with an object is
    described as single valued and the same field answering with a list is not, and a
    field answering with null is not even described as a relation. A declared schema
    has to hold for every response, so the root entities are built here against the
    declaration instead, and only the nested entities - which nothing was declared
    about - keep the shape the response gives them.

    A relation path therefore always carries a list of sub entity URIs, empty where
    the endpoint answered null, and a plain path always carries a list of values.
    """
    root_entities: list[Entity] = []
    sub_entities: list[Entities] = []
    for index, result in enumerate(payload):
        values: list[list[str]] = []
        for path in schema.paths:
            value = result.get(path.path)
            if not path.is_relation:
                values.append(_as_value_list(value))
                continue
            items = [item for item in _as_item_list(value) if isinstance(item, dict)]
            built = build_entities_from_data(items) if items else None
            if built is None:
                values.append([])
                continue
            entities = list(built.entities)
            values.append([entity.uri for entity in entities])
            built_collections = [
                Entities(entities=iter(entities), schema=built.schema),
                *(built.sub_entities or []),
            ]
            sub_entities.extend(_without_dangling_relations(_) for _ in built_collections)
        root_entities.append(Entity(uri=f"urn:x-graphql:result:{index}", values=values))
    return Entities(entities=iter(root_entities), schema=schema, sub_entities=sub_entities)


def _without_dangling_relations(entities: Entities) -> Entities:
    """Drop the placeholder that a null object leaves behind in a relation path

    `build_entities_from_data` calls a field a relation as soon as one item carries an
    object for it, and then writes `[""]` for every item where the endpoint answered
    null - GitLab does exactly that for a `createdByUser` nobody set. An empty string
    is not a sub entity URI, and a JSON dataset sink handed one fails the whole write
    with *Current context not Array but Object*, so the placeholder is removed and the
    path is left empty instead.
    """
    relations = [index for index, path in enumerate(entities.schema.paths) if path.is_relation]
    if not relations:
        return entities

    def cleaned() -> Iterator[Entity]:
        for entity in entities.entities:
            values = [list(value) for value in entity.values]
            for index in relations:
                values[index] = [uri for uri in values[index] if uri]
            yield Entity(uri=entity.uri, values=values)

    return Entities(entities=cleaned(), schema=entities.schema)


def _as_item_list(value: object) -> list[object]:
    """Read a relation value as the list of things behind it."""
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _as_value_list(value: object) -> list[str]:
    """Read a plain value as the list of strings behind it."""
    return [f"{item}" for item in _as_item_list(value)]


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
