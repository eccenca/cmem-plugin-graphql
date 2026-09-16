"""Utils module"""

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

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
    # A field selected twice at the top level - which happens as soon as two fragments
    # spread at the root ask for the same thing - is one key in the response, because
    # GraphQL merges the selections. Describing it twice would offer the next task a
    # duplicated path and build the same object twice.
    relations: dict[str, bool] = {}
    for selection in operations[0].selection_set.selections:
        if not isinstance(selection, FieldNode):
            return None
        name = selection.alias.value if selection.alias else selection.name.value
        relations[name] = relations.get(name, False) or selection.selection_set is not None
    return EntitySchema(
        type_uri="",
        paths=[
            EntityPath(path=name, is_relation=is_relation, is_single_value=False)
            for name, is_relation in relations.items()
        ],
    )


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

    The objects behind one relation path are built together, across every response of
    the run rather than one response at a time, so that path is described once. Built
    per response, a path answered with an object in one and with null in another comes
    out as two collections contradicting each other about the same path.
    """
    relation_paths = [path.path for path in schema.paths if path.is_relation]
    # what each response contributed to each path, as a slice of that path's objects
    objects: dict[str, list[dict[str, Any]]] = {name: [] for name in relation_paths}
    slices: list[dict[str, tuple[int, int]]] = []
    for result in payload:
        span: dict[str, tuple[int, int]] = {}
        for name in relation_paths:
            items = [_ for _ in _as_item_list(result.get(name)) if isinstance(_, dict)]
            start = len(objects[name])
            objects[name].extend(items)
            span[name] = (start, start + len(items))
        slices.append(span)

    sub_entities: list[Entities] = []
    built_entities: dict[str, list[Entity]] = {name: [] for name in relation_paths}
    for name in relation_paths:
        built = _build_sub_entities(objects[name], name) if objects[name] else None
        if built is None:
            continue
        built_entities[name] = list(built.entities)
        collections = [
            Entities(entities=iter(built_entities[name]), schema=built.schema),
            *(built.sub_entities or []),
        ]
        sub_entities.extend(_without_dangling_relations(_) for _ in collections)

    root_entities: list[Entity] = []
    for result, span in zip(payload, slices, strict=True):
        values: list[list[str]] = []
        for path in schema.paths:
            if not path.is_relation:
                values.append(_as_value_list(result.get(path.path)))
                continue
            start, end = span[path.path]
            values.append([_.uri for _ in built_entities[path.path][start:end]])
        # A run must not hand out identifiers another run, or another task in the same
        # workflow, also hands out: they would be taken for the same thing.
        root_entities.append(Entity(uri=f"urn:uuid:{uuid4()}", values=values))
    return Entities(entities=iter(root_entities), schema=schema, sub_entities=sub_entities)


def _build_sub_entities(objects: list[dict[str, Any]], path: str) -> Entities | None:
    """Build the entities behind one relation path, or say which path could not be built

    `build_entities_from_data` assumes a key holds the same kind of thing in every
    item, and walks into a value it decided is an object. A response where one record
    answers a field with text and another with an object - ordinary where a union type
    or a custom JSON scalar is involved - therefore fails inside the library with a
    bare `AttributeError`, after every query of the run has already been sent, and a
    mutation among them has already been carried out.
    """
    try:
        return build_entities_from_data(objects)
    except (AttributeError, TypeError) as error:
        raise ValueError(
            f"The response could not be turned into entities below '{path}': the endpoint "
            f"answered the same field with different kinds of value. Select the fields "
            f"individually, or take the result as a file instead. ({error})"
        ) from error


def without_dangling_relations(entities: Entities) -> Entities:
    """Clean a whole collection tree, root and nested alike

    The entities a derived schema produces are cleaned as they are built, but a query
    that describes no schema is handed to `build_entities_from_data` whole, and its
    result carries the same placeholder at every level.
    """
    return Entities(
        entities=_without_dangling_relations(entities).entities,
        schema=entities.schema,
        sub_entities=[_without_dangling_relations(_) for _ in entities.sub_entities or []],
    )


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
    """Read a plain value as the list of strings behind it

    Anything that is not already text is written as JSON rather than through Python's
    own formatting, which would hand on `True`, `None` and `{'k': 1}` where the
    endpoint answered `true`, `null` and an object. A field selected without sub
    fields can still answer with an object where the endpoint types it as a custom
    JSON scalar, and that object is then the JSON text of itself.
    """
    return [item if isinstance(item, str) else json.dumps(item) for item in _as_item_list(value)]


def get_dict(entities: Entities) -> Iterator[dict[str, str]]:
    """Get dict from entities"""
    paths = entities.schema.paths
    for entity in entities.entities:
        result = {}
        for i, path in enumerate(paths):
            result[path.path] = entity.values[i][0] if entity.values[i] else ""
        yield result


def render_template(template_text: str, values: dict[str, str]) -> str:
    """Render a Jinja template that produces GraphQL or JSON, not HTML

    Autoescaping is off. It is what `S701` asks for, and it is wrong here: it rewrites
    `&`, `<`, `>`, `"` and `'` in the rendered values, so a name like `O'Brien & Co`
    reaches the endpoint as `O&#39;Brien &amp; Co` - the query asks for something the
    user never typed, and a mutation stores it. Neither GraphQL nor JSON is HTML, and
    HTML escaping protects neither of them.

    Values are substituted as they are, so a value carrying a quote or a backslash can
    still break the JSON it lands in. Jinja's `tojson` filter is the way to place an
    untrusted or structured value safely.
    """
    environment = jinja2.Environment(autoescape=False)  # noqa: S701
    return environment.from_string(template_text).render(values)


def is_jinja_template(value: str) -> bool:
    """Check value contain jinja variables"""
    return render_template(value, {}) != value
