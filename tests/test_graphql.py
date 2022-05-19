"""Plugin tests."""
from cmem_plugin_graphql import GraphQLPlugin


def test_execution():
    """Test plugin execution"""
    pass
    url = "https://fruits-api.netlify.app/graphql"
    query = """
    query allFruits {
  fruits {
    id,
    scientific_name,
    fruit_name,
    description,
    producing_countries {
      country
    }
  }
}
"""
    dataset = "TestPlugins_d6f3594e5c9c450d:EmptyJSON_87bd1749821c429b"
    plugin = GraphQLPlugin(graphql_url=url, graphql_query=query, graphql_dataset=dataset)
    # TODO
    # result = plugin.execute()
