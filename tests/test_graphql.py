"""Plugin tests."""
from cmem_plugin_graphql import GraphQLPlugin

GRAPHQL_URL = 'https://fruits-api.netlify.app/graphql'

def test_execution():
    """Test plugin execution"""
    query = 'query allFruits{fruits{id,scientific_name,fruit_name,description,producing_countries{country}}}'

    # plugin = GraphQLPlugin(graphql_url=GRAPHQL_URL, graphql_query=query, graphql_dataset=dataset)
    # TODO
    # result = plugin.execute()
